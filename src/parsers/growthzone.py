# src/parsers/growthzone.py
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

CENTRAL_TZ = "America/Chicago"
HEADERS = {
    "User-Agent": "northwoods-events (+https://github.com/dsundt/northwoods-events)"
}

def _absolutize(base: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    return urljoin(base, href)

def _text(el) -> str:
    return re.sub(r"\s+", " ", (el.get_text(" ", strip=True) if el else "")).strip()

def _collect_from_list_view(url: str, html: str) -> List[Dict]:
    """
    Parse GrowthZone 'list' view (…/events/search?...).
    This view is server-rendered and much more stable than the month grid.
    """
    soup = BeautifulSoup(html, "lxml")

    rows: List[Dict] = []

    # Many GrowthZone list pages render each event within a container like:
    #  <div class="mn-event-item"> or within <li>…</li> with a heading link.
    # We'll be flexible: look for anchor/heading blocks with a date/time nearby.

    # Strategy:
    # 1) Identify each 'event card' by common wrappers; fallback to lis/divs with a link.
    candidates = []
    candidates += soup.select(".mn-event-item")
    if not candidates:
        candidates += soup.select("li.mn-event, li.mn-search-event, li.mn-event-item")
    if not candidates:
        # very permissive fallback: cards that have event title link
        candidates += soup.select("li, div")

    for card in candidates:
        # Title/link
        a = card.select_one("a[href*='/event/'], a[href*='/events/details'], a[href*='/events/']")
        if not a:
            # try a first link
            a = card.find("a", href=True)
        title = _text(a) if a else _text(card)
        if not title:
            continue
        link = _absolutize(url, a["href"]) if a else url

        # Date/time: often within elements with 'date' or 'time' classes, or plain text
        tparts = []
        for sel in [
            ".mn-event-date", ".mn-event-when", ".mn-event-time", ".mn-event-datetime",
            ".mn-list-when", ".mn-search-when", ".mn-eventtime", ".mn-event-date-time"
        ]:
            el = card.select_one(sel)
            if el:
                tparts.append(_text(el))
        date_text = " ".join([p for p in tparts if p]).strip()

        # Fallback: scan small-print text near the title
        if not date_text:
            near = a.find_parent(["div", "li"]) if a else card
            if near:
                smalls = near.find_all(["small", "time", "span"])
                for sm in smalls:
                    s = _text(sm)
                    if re.search(r"\b(am|pm|\d{4}|\bJan|\bFeb|\bMar|\bApr|\bMay|\bJun|\bJul|\bAug|\bSep|\bOct|\bNov|\bDec)", s, re.I):
                        date_text = s
                        break

        # Location (best-effort)
        loc = ""
        for sel in [".mn-event-location", ".mn-location", ".mn-event-where"]:
            el = card.select_one(sel)
            if el:
                loc = _text(el)
                break

        rows.append({
            "title": title,
            "date_text": date_text,
            "iso_hint": None,
            "iso_end_hint": None,
            "location": loc,
            "url": link,
            "source": url,
            "tzname": CENTRAL_TZ,
        })

    return rows

def _find_list_view_href(soup: BeautifulSoup) -> Optional[str]:
    """
    Find a link to GrowthZone 'list/search' view from a month grid page.
    """
    # Common texts or href patterns
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        txt = _text(a).lower()
        if "/events/search" in href or "list view" in txt or "events list" in txt:
            return href
    return None

def _collect_from_grid(url: str, html: str) -> List[Dict]:
    """
    Parse the GrowthZone MONTH GRID when a list view isn't available.
    Extract event links from grid cells and create lightweight rows.
    """
    soup = BeautifulSoup(html, "lxml")
    rows: List[Dict] = []

    # Typical selector:
    # <li class="mn-cal-event"> <a href="/events/details/…">Title</a> ... </li>
    for li in soup.select("li.mn-cal-event, .mn-cal-event"):
        a = li.find("a", href=True)
        if not a:
            continue
        title = _text(a)
        link = _absolutize(url, a["href"])

        # date might be in data attributes or nearby text; we'll stash raw text and
        # let normalize handle fuzzy parsing.
        date_text = ""
        # try a time or small meta span
        meta = li.select_one(".mn-cal-time, .mn-event-time, .mn-cal-meta, time")
        if meta:
            date_text = _text(meta)

        rows.append({
            "title": title,
            "date_text": date_text,
            "iso_hint": None,
            "iso_end_hint": None,
            "location": "",
            "url": link or url,
            "source": url,
            "tzname": CENTRAL_TZ,
        })

    return rows

def parse_growthzone(url: str, *, start: Optional[datetime] = None, end: Optional[datetime] = None, session: Optional[requests.Session] = None) -> List[Dict]:
    """
    Unified GrowthZone parser.

    - If the landing page is a month grid, we try to discover and follow the
      'Events List View' link for robust server-rendered HTML, else parse the grid.
    - If the landing page is already a list/search view, parse it directly.
    """
    sess = session or requests.Session()
    resp = sess.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    # If we're already on /events/search, parse as list view.
    if "/events/search" in urlparse(resp.url).path:
        return _collect_from_list_view(resp.url, html)

    soup = BeautifulSoup(html, "lxml")

    # Prefer list/search link if present
    list_href = _find_list_view_href(soup)
    if list_href:
        list_url = _absolutize(resp.url, list_href)
        if list_url:
            r2 = sess.get(list_url, headers=HEADERS, timeout=30)
            if r2.ok:
                return _collect_from_list_view(list_url, r2.text)

    # Otherwise parse grid (best-effort)
    rows = _collect_from_grid(resp.url, html)
    return rows
