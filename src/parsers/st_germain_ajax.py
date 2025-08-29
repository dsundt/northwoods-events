# -*- coding: utf-8 -*-
"""
St. Germain (Micronet/JS) parser:
- Try rendered DOM for obvious event links.
- Try ICS discovery if present.
"""

from typing import List, Dict
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .parse_simpleview import _parse_ics  # reuse ICS helper

def _abs(base: str, href: str) -> str:
    return urljoin(base, href)

def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")

    items: List[Dict] = []

    # 1) Try list/detail anchors on their domain that look like events
    for a in soup.select('a[href*="/events/"], a[href*="/events-calendar/"]'):
        href = a.get("href") or ""
        text = (a.get_text(" ", strip=True) or "").strip()
        if not href:
            continue
        items.append({
            "title": text or "Event",
            "start": "",
            "url": _abs(base_url, href),
            "location": "",
        })
    if items:
        return items

    # 2) Try ICS discovery
    ics_links = soup.select('a[href$=".ics"], a[href*="ical"], link[type="text/calendar"]')
    for link in ics_links:
        href = link.get("href") or ""
        if not href:
            continue
        events = _parse_ics(_abs(base_url, href))
        if events:
            return events

    return []
