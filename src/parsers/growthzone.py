from __future__ import annotations

from typing import List, Dict, Any, Optional, Iterable, Tuple, Set
from datetime import datetime
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from dateutil import parser as dtp

from parsers._text import text as _text
from utils.dates import parse_datetime_range  # returns (start_dt, end_dt) with end possibly None


MONTH_PAT = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(,\s*\d{4})?",
    re.IGNORECASE,
)

def _iso(dt: datetime) -> str:
    return dt.isoformat()

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _add(items: List[Dict[str, Any]], seen: Set[Tuple[str, str, str]], node: Dict[str, Any]) -> None:
    key = (node.get("title", ""), node.get("start", ""), node.get("url", ""))
    if all(key) and key not in seen:
        items.append(node)
        seen.add(key)

def _parse_jsonld(soup: BeautifulSoup, base_url: str) -> Iterable[Dict[str, Any]]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = script.string or script.get_text("", strip=True)
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue
        # JSON-LD may be a list, dict, or graph
        nodes = []
        if isinstance(data, list):
            nodes = data
        elif isinstance(data, dict):
            nodes = data.get("@graph") or [data]
        else:
            continue

        for n in nodes:
            try:
                t = (n.get("@type") or n.get("type") or "")
                if isinstance(t, list):
                    is_event = any(str(x).lower() == "event" for x in t)
                else:
                    is_event = str(t).lower() == "event"
                if not is_event:
                    continue

                title = _clean(n.get("name") or "")
                start_raw = n.get("startDate") or n.get("startTime") or ""
                end_raw = n.get("endDate") or n.get("endTime") or ""
                url = urljoin(base_url, n.get("url") or "")
                loc = ""
                location = n.get("location")
                if isinstance(location, dict):
                    loc = _clean(location.get("name") or location.get("address", "") or "")
                elif isinstance(location, str):
                    loc = _clean(location)

                if not (title and start_raw and url):
                    continue

                start_dt = dtp.parse(start_raw)
                end_dt = None
                if end_raw:
                    try:
                        end_dt = dtp.parse(end_raw)
                    except Exception:
                        end_dt = None

                yield {
                    "title": title,
                    "start": _iso(start_dt),
                    **({"end": _iso(end_dt)} if end_dt else {}),
                    "location": loc,
                    "url": url,
                }
            except Exception:
                # Don't let one bad node break parsing
                continue

def _guess_date_block(container: Tag) -> str:
    """
    Pull a likely date string from GrowthZone list cards. They vary a lot.
    """
    candidate_classes = [
        "date", "gz-date", "gz-event__date", "gzc_event_date", "gj-list__date",
        "event-date", "eventDate", "list-date"
    ]
    # direct candidates
    for c in candidate_classes:
        n = container.find(class_=re.compile(rf"\b{re.escape(c)}\b", re.I))
        if n:
            s = _text(n)
            if MONTH_PAT.search(s):
                return s

    # look in small/strong tags near the title
    for n in container.find_all(["small", "strong", "span", "div"], limit=8):
        s = _text(n)
        if MONTH_PAT.search(s):
            return s

    # fallback: any text in container that looks like a date
    s = _text(container)
    m = MONTH_PAT.search(s)
    return m.group(0) if m else ""

def _parse_dom(soup: BeautifulSoup, base_url: str) -> Iterable[Dict[str, Any]]:
    """
    Common GrowthZone list patterns:
      - anchor to '/events/details/...'
      - date block in sibling element
    """
    # Find event links
    link_sel = soup.find_all("a", href=True)
    for a in link_sel:
        href = a["href"]
        if not re.search(r"/events?/details?/", href, re.I):
            continue

        title = _clean(_text(a))
        if not title:
            # sometimes title is nested deeper
            inner = a.find(["h2", "h3"])
            title = _clean(_text(inner)) if inner else ""

        if not title:
            continue

        url = urljoin(base_url, href)

        # Find a nearby container to grab date/location
        container = a
        for _ in range(3):
            if container and container.parent:
                container = container.parent
            else:
                break

        date_txt = _guess_date_block(container or a)
        start_dt = end_dt = None

        if date_txt:
            # Try "start - end" first
            try:
                s, e = parse_datetime_range(date_txt)
                start_dt, end_dt = s, e
            except Exception:
                # Try single date
                try:
                    start_dt = dtp.parse(date_txt, fuzzy=True)
                except Exception:
                    start_dt = None

        if not start_dt:
            # Sometimes GrowthZone puts ISO-ish dates in data-attrs
            attrs = " ".join(f"{k}={v}" for k, v in (container or a).attrs.items())
            m = re.search(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?", attrs)
            if m:
                try:
                    start_dt = dtp.parse(m.group(0))
                except Exception:
                    pass

        if not start_dt:
            # If we still don't have a date, skip this entry
            continue

        # location heuristics
        loc = ""
        for cls in ["location", "gz-location", "event-location", "gj-list__location"]:
            n = (container or a).find(class_=re.compile(rf"\b{cls}\b", re.I))
            if n:
                loc = _clean(_text(n))
                break

        node: Dict[str, Any] = {
            "title": title,
            "start": _iso(start_dt),
            "url": url,
        }
        if end_dt:
            node["end"] = _iso(end_dt)
        if loc:
            node["location"] = loc

        yield node

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Parse GrowthZone/ChamberMaster calendars (e.g., Rhinelander).
    Strategy:
      1) JSON-LD Event blocks (if present)
      2) DOM listing cards with '/events/details/' anchors + date siblings
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, str]] = set()

    for node in _parse_jsonld(soup, base_url):
        _add(items, seen, node)

    # Even if JSON-LD existed, DOM sometimes has additional items (or better urls)
    for node in _parse_dom(soup, base_url):
        _add(items, seen, node)

    return items
