from __future__ import annotations
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from .utils import soupify, clean_text, abs_url
from urllib.parse import urljoin
import re

def _find_ics_url(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    # Look for .ics links or export endpoints
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        h = href.lower()
        if ".ics" in h or "ical" in h or "ics=" in h or "export" in h:
            return abs_url(base_url, href)
    return None

def _parse_cards(soup: BeautifulSoup, base_url: str, source_name: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cards = soup.select("article, .event-card, li.event, .sv-event")
    for c in cards:
        a = c.select_one("a[href]")
        title_el = c.select_one("h3, h2, .title")
        time_el = c.select_one("time[datetime], meta[itemprop='startDate']")
        title = clean_text((title_el or a).get_text() if (title_el or a) else "")
        start = ""
        if time_el and time_el.has_attr("datetime"):
            start = time_el["datetime"]
        elif time_el and time_el.has_attr("content"):
            start = time_el["content"]
        url = abs_url(base_url, a["href"]) if a and a.has_attr("href") else None
        loc_el = c.select_one(".location, .venue")
        loc = clean_text(loc_el.get_text()) if loc_el else ""
        if title and start:
            out.append({
                "title": title,
                "start": start,
                "end": None,
                "location": loc,
                "url": url,
                "source": source_name,
            })
    return out

def parse_simpleview(html: str, base_url: str, tzname: Optional[str], source_name: str) -> List[Dict[str, Any]]:
    soup = soupify(html)
    # Try ICS link first
    ics_url = _find_ics_url(soup, base_url)
    if ics_url:
        # Defer to ICS parser by fetching content here to keep module-local
        import requests
        r = requests.get(ics_url, timeout=60)
        if r.ok:
            from .ics_feed import parse_ics
            return parse_ics(r.text, tzname=tzname, source_name=source_name)
    # Fallback to parsing visible cards
    return _parse_cards(soup, base_url, source_name)
