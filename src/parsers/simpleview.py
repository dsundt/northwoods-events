# src/parsers/simpleview.py
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CENTRAL_TZ = "America/Chicago"
HEADERS = {
    "User-Agent": "northwoods-events (+https://github.com/dsundt/northwoods-events)"
}

def _fmt_mmddyyyy(d: datetime) -> str:
    return d.strftime("%-m/%-d/%Y") if "%" in "%-m" else d.strftime("%m/%d/%Y")

def _absolutize(base: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    return urljoin(base, href)

def _text(el) -> str:
    return re.sub(r"\s+", " ", (el.get_text(" ", strip=True) if el else "")).strip()

def _build_print_url(base_url: str, start: datetime, end: datetime) -> str:
    # Simpleview exposes a server-rendered print view that the site itself builds.
    # /print-events/?startDate=MM/DD/YYYY&endDate=MM/DD/YYYY
    root = base_url.rstrip("/")
    start_s = _fmt_mmddyyyy(start)
    end_s = _fmt_mmddyyyy(end)
    return f"{root}/print-events/?startDate={start_s}&endDate={end_s}"

def parse_simpleview(base_url: str, *, window_days: int = 180, session: Optional[requests.Session] = None) -> List[Dict]:
    """
    Fetch the Simpleview 'print-events' HTML for a date window and parse it.
    Works for Minocqua (simpleview).
    """
    sess = session or requests.Session()
    now = datetime.utcnow()
    start = now
    end = now + timedelta(days=window_days)

    print_url = _build_print_url(base_url, start, end)
    resp = sess.get(print_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    soup = BeautifulSoup(html, "lxml")
    rows: List[Dict] = []

    # The print view typically renders a list of events with title links and a block of
    # date/time text. We'll be permissive with selectors.
    event_blocks = soup.select("article, .event, .sv-event, .listing, li")
    if not event_blocks:
        event_blocks = soup.find_all(["div", "li", "article"])

    for blk in event_blocks:
        a = blk.find("a", href=True)
        title = _text(a) if a else _text(blk)
        if not title:
            continue

        link = _absolutize(print_url, a["href"]) if a else base_url

        # Try to find a date/time string near the title
        date_text = ""
        # Common patterns: <time>, or spans with 'date', 'time'
        time_el = blk.find("time")
        if time_el:
            date_text = _text(time_el)

        if not date_text:
            # search small/meta blocks
            for sel in [".date", ".time", ".datetime", ".event-date", ".event-time"]:
                el = blk.select_one(sel)
                if el:
                    date_text = _text(el)
                    break

        # Fallback: use entire block text (noisy but normalize.py handles it)
        if not date_text:
            date_text = _text(blk)

        # Location (best-effort)
        location = ""
        for sel in [".location", ".event-location", ".venue"]:
            el = blk.select_one(sel)
            if el:
                location = _text(el)
                break

        rows.append({
            "title": title,
            "date_text": date_text,
            "iso_hint": None,
            "iso_end_hint": None,
            "location": location,
            "url": link,
            "source": print_url,
            "tzname": CENTRAL_TZ,
        })

    return rows
