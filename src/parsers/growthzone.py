from __future__ import annotations

import time
import requests
from bs4 import BeautifulSoup
from typing import Iterable, Dict, Any

from normalize import parse_datetime_range, clean_text
from .utils import absolutize

DEFAULT_TIMEOUT = 12
RETRIES = 2
BACKOFF = 2.0

def fetch_html(url: str) -> str:
    last = None
    for i in range(RETRIES + 1):
        try:
            r = requests.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            time.sleep(BACKOFF * (i + 1))
    raise last

def parse(html: str, base_url: str) -> Iterable[Dict[str, Any]]:
    """
    GrowthZone calendar: handle server HTML (not the JSON API).
    """
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select(".gz-list-item, .calendar-item, .event-list-item")
    if not rows:
        try:
            live = fetch_html(base_url)
            soup = BeautifulSoup(live, "lxml")
            rows = soup.select(".gz-list-item, .calendar-item, .event-list-item")
        except Exception:
            rows = []

    for r in rows:
        a = r.select_one("a[href]")
        if not a:
            continue
        url = absolutize(base_url, a["href"])
        title = clean_text(a.get_text(" ", strip=True))
        if not title:
            continue

        date_text = ""
        for sel in [".date", ".eventDate", ".calendar-date", ".gz-list-item-date"]:
            el = r.select_one(sel)
            if el:
                date_text = clean_text(el.get_text(" ", strip=True))
                break

        start_dt, end_dt, all_day = parse_datetime_range(date_text=date_text, tzname="America/Chicago")

        loc = ""
        for sel in [".location", ".venue", ".eventLocation"]:
            el = r.select_one(sel)
            if el:
                loc = clean_text(el.get_text(" ", strip=True))
                break

        yield {
            "title": title,
            "url": url,
            "location": loc,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "all_day": all_day,
        }
