# -*- coding: utf-8 -*-
"""
Simpleview parser:
- First tries rendered DOM (event cards/links).
- Then tries to discover an ICS feed in-page.
- Finally tries common ICS URLs or falls back to obvious anchors.
"""

from typing import List, Dict
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import re
import requests

def _abs(base: str, href: str) -> str:
    return urljoin(base, href)

def _ics_candidates(base_url: str) -> List[str]:
    u = base_url.rstrip("/")
    return [
        f"{u}?format=ical",
        f"{u}?format=ics",
        f"{u}?ical=1",
        f"{u}?ical=true",
        f"{u}/?format=ical",
        f"{u}/?format=ics",
        f"{u}/?ical=1",
        f"{u}/?ical=true",
    ]

def _parse_ics(url: str) -> List[Dict]:
    try:
        from ics import Calendar
        import requests
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        cal = Calendar(r.text)
        out = []
        for e in cal.events:
            start = ""
            try:
                # Prefer naive ISO (UTC or local naive acceptable for your pipeline)
                start = e.begin.datetime.isoformat(timespec="seconds")
            except Exception:
                pass
            out.append({
                "title": (e.name or "").strip(),
                "start": start,
                "url": (e.url or url).strip(),
                "location": (e.location or "").strip(),
            })
        return out
    except Exception:
        return []

def parse_simpleview(html: str, base_url: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")

    # Strategy 1: rendered DOM – find event anchors that look like /event/... pages
    anchors = soup.select('a[href*="/event/"]')
    items: List[Dict] = []
    seen = set()
    for a in anchors:
        href = a.get("href") or ""
        text = (a.get_text(" ", strip=True) or "").strip()
        if not href:
            continue
        href_abs = _abs(base_url, href)
        # Guard against nav/crumbs: require some non-trivial title text
        if len(text) < 3:
            continue
        key = (text.lower(), href_abs)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": text,
            "start": "",           # date extraction differs by theme; leave blank if not obvious
            "url": href_abs,
            "location": "",
        })

    if items:
        return items

    # Strategy 2: discover ICS feed in page
    ics_links = soup.select('a[href$=".ics"], a[href*="ical"], a[href*="ICS"], link[type="text/calendar"]')
    for link in ics_links:
        href = link.get("href") or ""
        if not href:
            continue
        ics_url = _abs(base_url, href)
        events = _parse_ics(ics_url)
        if events:
            return events

    # Strategy 3: try common ICS URLs
    for guess in _ics_candidates(base_url):
        events = _parse_ics(guess)
        if events:
            return events

    # Strategy 4: last resort – any on-page links that look like “events” section
    more = soup.select('a[href*="/events/"]')
    for a in more:
        href = a.get("href") or ""
        text = (a.get_text(" ", strip=True) or "").strip() or "Events |"
        if not href:
            continue
        items.append({
            "title": text,
            "start": "",
            "url": _abs(base_url, href),
            "location": "",
        })
    return items
