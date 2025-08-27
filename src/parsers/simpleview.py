# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any
from bs4 import BeautifulSoup
import re

from .common_ldjson import extract_events_from_ldjson

def parse(html: str) -> List[Dict[str, Any]]:
    """
    Simpleview CVB pages:
    1) Prefer JSON-LD Events (commonly present)
    2) Fallback to common Simpleview card selectors
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
    # Typical Simpleview list cards (varies by theme)
    cards = soup.select(".event-card, .sv-event, .m-event, .c-card--event, .card--event, li.event, div.event")
    for c in cards:
        title_el = c.select_one("a[href], .card__title a, h3 a, h2 a")
        date_el  = c.select_one(".date, .event-date, time, .card__date")
        where_el = c.select_one(".location, .event-location, .card__meta, .venue")
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
