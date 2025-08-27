# -*- coding: utf-8 -*-
"""
Modern Tribe (The Events Calendar) HTML parser with JSON-LD first strategy.

- Prefer schema.org Event objects embedded in <script type="application/ld+json">.
- Fallback to common Modern Tribe list view DOM when JSON-LD not present.
- Produces rows of dicts with keys: title, url, location, date_text, iso_hint, iso_end_hint.

Assumes upstream main.py will call normalize.parse_datetime_range() on iso hints.
"""
from __future__ import annotations

import json
import re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

def _coerce_event(obj: Any) -> Optional[Dict[str, Any]]:
    """Return an Event-like dict from a JSON-LD entity if it looks like an Event."""
    if not isinstance(obj, dict):
        return None
    t = obj.get("@type")
    if isinstance(t, list):
        is_event = any(tt.lower() == "event" for tt in map(str, t))
    else:
        is_event = (str(t).lower() == "event")
    if not is_event:
        return None

    name = (obj.get("name") or "").strip()
    url = (obj.get("url") or "").strip()
    start = (obj.get("startDate") or "").strip()
    end = (obj.get("endDate") or "").strip()
    location = ""
    loc = obj.get("location")
    if isinstance(loc, dict):
        location = (loc.get("name") or loc.get("address") or "").strip()
    elif isinstance(loc, list) and loc:
        l0 = loc[0]
        if isinstance(l0, dict):
            location = (l0.get("name") or l0.get("address") or "").strip()
    if not name or not start:
        return None
    return {
        "title": name,
        "url": url,
        "location": location,
        "date_text": "",              # not needed when iso hints are available
        "iso_hint": start,
        "iso_end_hint": end or "",
    }

def _iter_jsonld_events(soup: BeautifulSoup):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = (tag.string or tag.get_text() or "").strip()
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            # Some sites wrap multiple JSON objects; try bracket patch
            try:
                data = json.loads(re.sub(r"}\s*{", "},{", txt))
            except Exception:
                continue

        # Data might be dict, list, graph, etc.
        candidates: List[Dict[str, Any]] = []
        if isinstance(data, list):
            for it in data:
                ev = _coerce_event(it)
                if ev:
                    candidates.append(ev)
        elif isinstance(data, dict):
            # direct event
            ev = _coerce_event(data)
            if ev:
                candidates.append(ev)
            # graph form
            graph = data.get("@graph")
            if isinstance(graph, list):
                for it in graph:
                    ev = _coerce_event(it)
                    if ev:
                        candidates.append(ev)
        for c in candidates:
            yield c

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def parse(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")

    rows: List[Dict[str, Any]] = []

    # 1) JSON-LD first (very reliable on Modern Tribe)
    for ev in _iter_jsonld_events(soup):
        rows.append(ev)

    if rows:
        return rows

    # 2) DOM fallback for list view
    # Common wrappers: .tribe-events-calendar-list__event or article.tribe-events-calendar-list__event
    for ev in soup.select(".tribe-events-calendar-list__event, article.tribe-events-calendar-list__event"):
        title = _clean((ev.select_one(".tribe-events-calendar-list__event-title, .tribe-events-list-event-title, h3 a, h3") or {}).get_text() if ev else "")
        link = ev.select_one("a")
        url = _clean(link.get("href") if link else "")

        # Modern Tribe often includes data-start-datetime/end in attributes
        start_attr = (ev.get("data-start-datetime") or "").strip()
        end_attr = (ev.get("data-end-datetime") or "").strip()

        # Or the time block contains <time> elements with datetime=
        time_tag_start = ev.select_one("time[datetime]")
        time_tag_end = None
        # A second time element if present
        times = ev.select("time[datetime]")
        if len(times) >= 2:
            time_tag_end = times[1]

        iso_hint = start_attr or (time_tag_start.get("datetime").strip() if time_tag_start else "")
        iso_end_hint = end_attr or (time_tag_end.get("datetime").strip() if time_tag_end else "")

        venue = _clean((ev.select_one(".tribe-events-venue-details, .tribe-events-calendar-list__event-venue") or {}).get_text() if ev else "")

        if title and (iso_hint or url):
            rows.append({
                "title": title,
                "url": url,
                "location": venue,
                "date_text": "",
                "iso_hint": iso_hint,
                "iso_end_hint": iso_end_hint,
            })

    return rows
