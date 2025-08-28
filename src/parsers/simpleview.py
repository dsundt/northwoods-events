from __future__ import annotations

from typing import List, Dict, Any, Optional
from datetime import datetime
import json, re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dateutil import parser as dtp

from parsers._text import text as _text  # shared helper

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
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            if "@graph" in obj and isinstance(obj["@graph"], list):
                objs.extend([g for g in obj["@graph"] if isinstance(g, dict)])
                continue
            if (obj.get("@type") or "").lower() != "event":
                continue
            name = obj.get("name") or obj.get("headline") or ""
            if not name:
                continue
            start_raw = obj.get("startDate")
            end_raw = obj.get("endDate")
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
            loc = ""
            loc_obj = obj.get("location")
            if isinstance(loc_obj, dict):
                loc = loc_obj.get("name") or ""
                addr = loc_obj.get("address")
                if isinstance(addr, dict):
                    parts = [addr.get("streetAddress") or "", addr.get("addressLocality") or "", addr.get("addressRegion") or ""]
                    parts = [p for p in parts if p]
                    if parts:
                        loc = (loc + ", " + ", ".join(parts)).strip(", ")
            elif isinstance(loc_obj, str):
                loc = loc_obj
            url = urljoin(base_url, obj.get("url") or "")
            out.append(_norm(name, start, end, loc, url or base_url))
    return out

def _parse_dom(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    """
    Simpleview fallback parser:
    - Looks for common event card wrappers and date attributes/text
    """
    out: List[Dict[str, Any]] = []
    cards = soup.select(".event, .events-item, .sv-event, .sv-listing, article, li")
    for c in cards:
        a = c.find("a", href=True)
        title = _text(a) if a else _text(c.find(class_=re.compile("title|name|heading", re.I)))
        title = (title or "").strip()
        if not title:
            continue

        # Datetime candidates
        dt_node = c.find("time")
        dt_txt = ""
        if dt_node:
            dt_txt = dt_node.get("datetime") or _text(dt_node) or ""
        if not dt_txt:
            # attributes many sites use
            for attr in ("data-start", "data-startdate", "data-start-time", "data-date"):
                if c.has_attr(attr):
                    dt_txt = c.get(attr) or ""
                    break
        if not dt_txt:
            # scan small text for Month names or numeric dates
            for probe in c.find_all(["span", "div", "p", "small"]):
                t = _text(probe)
                if re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{1,2}/\d{1,2}/\d{2,4})\b", t, re.I):
                    dt_txt = t
                    break

        start_dt = None
        if dt_txt:
            try:
                start_dt = dtp.parse(dt_txt, fuzzy=True)
            except Exception:
                start_dt = None
        if not start_dt:
            continue

        loc_node = c.find(class_=re.compile("venue|location|address", re.I))
        loc = _text(loc_node) if loc_node else ""
        href = urljoin(base_url, a["href"]) if a else base_url
        out.append(_norm(title, start_dt, None, loc, href))
    return out

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    # 1) JSON-LD (often present on Simpleview sites)
    for n in _parse_jsonld(soup, base_url):
        key = (n["title"], n["start"], n["url"])
        if key not in seen:
            items.append(n); seen.add(key)

    # 2) DOM fallback
    if not items:
        for n in _parse_dom(soup, base_url):
            key = (n["title"], n["start"], n["url"])
            if key not in seen:
                items.append(n); seen.add(key)

    return items
