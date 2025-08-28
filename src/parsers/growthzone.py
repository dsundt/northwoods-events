from __future__ import annotations

from typing import List, Dict, Any, Optional
from datetime import datetime
import json, re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dateutil import parser as dtp

from parsers._text import text as _text  # safe helper used elsewhere
# Keep this parser self-contained (no extra utils import)

def _iso(dt: datetime) -> str:
    return dt.isoformat()

def _norm(title: str, start: datetime, end: Optional[datetime], location: str, url: str) -> Dict[str, Any]:
    return {
        "title": title.strip(),
        "start": _iso(start),
        "end": _iso(end or start),
        "location": (location or "").strip(),
        "url": url,
    }

def _parse_jsonld(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        # Could be a list or a single object
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            typ = obj.get("@type") or obj.get("@context")
            if not typ:
                continue
            # Handle nested graph
            graph = obj.get("@graph")
            if isinstance(graph, list):
                objs.extend([x for x in graph if isinstance(x, dict)])
                continue
            if (obj.get("@type") or "").lower() != "event":
                continue
            name = obj.get("name") or obj.get("headline") or ""
            if not name:
                continue
            start_raw = obj.get("startDate") or obj.get("start_time") or obj.get("date")
            end_raw = obj.get("endDate") or obj.get("end_time")
            try:
                start = dtp.parse(str(start_raw))
            except Exception:
                continue
            end = None
            if end_raw:
                try:
                    end = dtp.parse(str(end_raw))
                except Exception:
                    end = None
            # location object or string
            loc = ""
            loc_obj = obj.get("location")
            if isinstance(loc_obj, dict):
                loc = loc_obj.get("name") or ""
                addr = loc_obj.get("address")
                if isinstance(addr, dict):
                    part = ", ".join([addr.get("streetAddress") or "", addr.get("addressLocality") or ""]).strip(", ")
                    if part:
                        loc = (loc + ", " + part).strip(", ")
            elif isinstance(loc_obj, str):
                loc = loc_obj
            url = obj.get("url") or ""
            url = urljoin(base_url, url) if url else base_url
            out.append(_norm(name, start, end, loc, url))
    return out

def _parse_microdata(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for scope in soup.select('[itemtype*="schema.org/Event"], [itemscope][itemtype*="Event"]'):
        name = (scope.select_one('[itemprop="name"]') or scope.select_one('[itemprop="summary"]'))
        start = scope.select_one('[itemprop="startDate"], time[itemprop="startDate"]')
        end = scope.select_one('[itemprop="endDate"], time[itemprop="endDate"]')
        loc_node = scope.select_one('[itemprop="location"]')
        url_node = scope.select_one('[itemprop="url"], a[href]')
        try:
            title = _text(name) if name else ""
            if not title:
                continue
            start_val = start.get("content") if start else None
            if not start_val:
                start_val = _text(start) if start else None
            if not start_val:
                continue
            start_dt = dtp.parse(start_val)
            end_dt = None
            if end:
                end_val = end.get("content") or _text(end)
                try:
                    end_dt = dtp.parse(end_val) if end_val else None
                except Exception:
                    end_dt = None
            loc = _text(loc_node) if loc_node else ""
            href = url_node.get("href") if url_node and url_node.has_attr("href") else ""
            href = urljoin(base_url, href) if href else base_url
            out.append(_norm(title, start_dt, end_dt, loc, href))
        except Exception:
            continue
    return out

def _parse_dom_cards(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    """
    Generic GrowthZone HTML fallback:
    - Looks for common card/list patterns with a date area + title link.
    """
    out: List[Dict[str, Any]] = []
    # Common wrappers
    wrappers = soup.select(".gz-event, .event, .calendar-event, .card, li, article")
    for w in wrappers:
        # title link
        a = w.find("a", href=True)
        title = _text(a) if a else ""
        if not title:
            continue
        # Find a nearby date text
        dt_node = w.find(["time", "span", "div"], attrs={"datetime": True})
        dt_txt = dt_node.get("datetime") if dt_node and dt_node.has_attr("datetime") else ""
        if not dt_txt:
            # fallback to text scan
            dt_txt = ""
            for probe in w.find_all(["time", "span", "div", "p", "small"]):
                t = _text(probe)
                if re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{1,2}/\d{1,2}/\d{2,4})\b", t, re.I):
                    dt_txt = t
                    break
        try:
            start_dt = dtp.parse(dt_txt, fuzzy=True) if dt_txt else None
        except Exception:
            start_dt = None
        if not start_dt:
            continue
        loc_node = w.find(class_=re.compile("venue|location", re.I))
        loc = _text(loc_node) if loc_node else ""
        href = urljoin(base_url, a["href"]) if a else base_url
        out.append(_norm(title, start_dt, None, loc, href))
    return out

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()

    # 1) JSON-LD
    for n in _parse_jsonld(soup, base_url):
        key = (n["title"], n["start"], n["url"])
        if key not in seen:
            items.append(n); seen.add(key)

    # 2) Microdata
    for n in _parse_microdata(soup, base_url):
        key = (n["title"], n["start"], n["url"])
        if key not in seen:
            items.append(n); seen.add(key)

    # 3) Generic DOM fallback
    if not items:
        for n in _parse_dom_cards(soup, base_url):
            key = (n["title"], n["start"], n["url"])
            if key not in seen:
                items.append(n); seen.add(key)

    return items
