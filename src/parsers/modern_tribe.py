# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any
from bs4 import BeautifulSoup
import re

from .common_ldjson import extract_events_from_ldjson

def parse(html: str) -> List[Dict[str, Any]]:
    """
    WordPress 'The Events Calendar' (Modern Tribe) – robust:
    1) Prefer schema.org JSON-LD Events
    2) Fallback to DOM patterns used by Classic/Blocks list views
    Returns normalized rows with keys: title, date_text, iso_hint, iso_end_hint, url, location
    """
    rows: List[Dict[str, Any]] = []

    # 1) JSON-LD first (covers most sites)
    ld = extract_events_from_ldjson(html)
    for ev in ld:
        rows.append({
            "title": ev["title"],
            "date_text": "",                 # normalize.py will rely on ISO hints when present
            "iso_hint": ev["start_iso"],
            "iso_end_hint": ev.get("end_iso"),
            "url": ev.get("url", ""),
            "location": ev.get("location", ""),
        })
    if rows:
        return rows

    # 2) Very forgiving HTML fallback
    soup = BeautifulSoup(html or "", "lxml")

    # Newer TEC list view
    cards = soup.select("[class*='tribe-events-calendar-list__event']") or \
            soup.select("[class*='tribe-common-g-row'] [class*='tribe-events-calendar-list__event']")
    for c in cards:
        title_el = c.select_one("h3 a, h2 a, a[class*='tribe-events-calendar-list__event-title-link']")
        date_el = c.select_one("[class*='tribe-events-calendar-list__event-date'], time, .tribe-event-date-start")
        where_el = c.select_one("[class*='venue'], [class*='tribe-events-calendar-list__event-venue']")
        title = (title_el.get_text(strip=True) if title_el else "").strip()
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

    # Older TEC (v5/v6 mix)
    if not rows:
        items = soup.select(".tribe-events-calendar-list__event, .type-tribe_events")
        for c in items:
            title_el = c.select_one(".tribe-event-title a, .tribe-events-event-title a, h2 a, h3 a")
            date_el = c.select_one("time, .tribe-event-date-start, .tribe-events-event-datetime")
            where_el = c.select_one(".tribe-venue, .tribe-events-venue-details, .tribe-venue-location")
            title = (title_el.get_text(strip=True) if title_el else "").strip()
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

    # De-dup by title+url
    seen = set()
    deduped = []
    for r in rows:
        k = (r["title"], r.get("url",""))
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)
    return deduped
