# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any
from bs4 import BeautifulSoup
import re

from .common_ldjson import extract_events_from_ldjson

def parse(html: str) -> List[Dict[str, Any]]:
    """
    GrowthZone calendars are often JS-driven. We attempt:
    1) JSON-LD Events (some chambers inject schema)
    2) Static fallbacks for server-rendered calendars (when present)
    """
    rows: List[Dict[str, Any]] = []

    ld = extract_events_from_ldjson(html)
    for ev in ld:
        rows.append({
            "title": ev["title"],
            "date_text": "",
            "iso_hint": ev["start_iso"],
            "iso_end_hint": ev.get("end_iso"),
            "url": ev.get("url", ""),
            "location": ev.get("location", ""),
        })
    if rows:
        return rows

    soup = BeautifulSoup(html or "", "lxml")
    # Fallback guesses: some GrowthZone sites render a basic server list
    items = soup.select(".gz_event, .event-item, li.event, .calendar-item, .list-item")
    for it in items:
        title_el = it.select_one("a[href], .event-title a, h3 a, h2 a")
        date_el  = it.select_one("time, .event-date, .dates")
        where_el = it.select_one(".location, .venue")
        title = (title_el.get_text(" ", strip=True) if title_el else "").strip()
        url = (title_el.get("href").strip() if title_el and title_el.has_attr("href") else "")
        date_text = (date_el.get_text(" ", strip=True) if date_el else "").strip()
        location = (where_el.get_text(" ", strip=True) if where_el else "").strip()
        if title:
            rows.append({
                "title": title,
                "date_text": date_text,
                "iso_hint": None,
                "iso_end_hint": None,
                "url": url,
                "location": location,
            })

    # Dedup
    seen = set()
    out = []
    for r in rows:
        k = (r["title"], r.get("url",""))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out
