#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Defensive GrowthZone events scraper (drop-in).
- Hardened HTTP (retries, timeouts, backoff, sane headers)
- Strict result schema & validation
- Parse guarded against template/CMS changes
- Clear error signaling without raising on "normal" site drift
- CLI for smoke testing
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import random
import re
import sys
import time
from typing import Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -------- Logging --------
LOG = logging.getLogger("growthzone")
if not LOG.handlers:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [growthzone] %(message)s"))
    LOG.addHandler(h)
LOG.setLevel(logging.INFO)

# -------- Config / Tunables --------
DEFAULT_TIMEOUT = (6.1, 20.0)  # (connect, read) seconds
MAX_RETRIES = 5
BACKOFF_FACTOR = 0.6
STATUS_FORCELIST = (429, 500, 502, 503, 504)
ALLOWED_DOMAINS = (
    "growthzoneapp.com",
    "growthzone.com",
    "business.",  # common subdomain prefix for chambers
)

USER_AGENTS = [
    # rotate a few reasonable UAs; keep list short (deterministic) but varied
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
]

# -------- Data Model --------
@dataclasses.dataclass
class Event:
    title: str
    start: Optional[dt.datetime]
    end: Optional[dt.datetime]
    location: Optional[str]
    url: Optional[str]
    description: Optional[str] = None
    source: str = "growthzone"

    def as_dict(self) -> dict:
        return {
            "title": self.title.strip() if self.title else "",
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "location": (self.location or "").strip() or None,
            "url": (self.url or "").strip() or None,
            "description": (self.description or "").strip() or None,
            "source": self.source,
        }

# -------- HTTP Session (defensive) --------
def _build_session() -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=STATUS_FORCELIST,
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    return sess

# -------- Helpers --------
_GZ_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?")

def _parse_dt(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    s = s.strip()
    try:
        # Try GrowthZone's common datetime attributes (ISO-ish)
        m = _GZ_DATE_RE.search(s)
        if m:
            y, mo, d, hh, mm = m.groups()
            if hh and mm:
                return dt.datetime(int(y), int(mo), int(d), int(hh), int(mm))
            return dt.datetime(int(y), int(mo), int(d))
        # Fallback: let fromisoformat try
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None

def _domain_is_expected(url: str) -> bool:
    return any(part in (url or "") for part in ALLOWED_DOMAINS)

# -------- Core Scrape --------
def fetch_events(calendar_url: str, limit: Optional[int] = None) -> Tuple[List[Event], List[str]]:
    """
    Returns (events, warnings). Does not raise on expected content drift.
    """
    warnings: List[str] = []
    events: List[Event] = []

    if not _domain_is_expected(calendar_url):
        warnings.append("URL domain not recognized for GrowthZone—attempting anyway.")
    sess = _build_session()

    try:
        resp = sess.get(calendar_url, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as e:
        warnings.append(f"Network error: {e.__class__.__name__}")
        LOG.warning("Network error fetching %s: %s", calendar_url, e)
        return [], warnings

    if resp.status_code >= 400:
        warnings.append(f"HTTP {resp.status_code} from server")
        LOG.warning("HTTP %s for %s", resp.status_code, calendar_url)
        if resp.status_code in (403, 429):
            # likely bot protection / rate limiting
            time.sleep(1.5)
        if not resp.text:
            return [], warnings

    soup = BeautifulSoup(resp.text, "html.parser")

    # Strategy 1: structured data blocks common to GrowthZone calendars
    cards = soup.select('[data-cg-event], .gz-event, .card.event, .event-list-item')
    if not cards:
        warnings.append("No obvious event containers found; template may have changed.")
        LOG.info("Fallback to generic list parsing.")
        cards = soup.select("article, .event, li")[:200]  # soft cap

    for card in cards:
        try:
            title = (
                (card.get("data-cg-event-title")
                 or card.select_one(".event-title, .gz-event-title, h3, h2, a").get_text(strip=True))
                if card else ""
            )
        except Exception:
            title = ""

        try:
            url_el = card.select_one("a[href*='event'], a[href*='Event']")
            url = url_el["href"].strip() if url_el and url_el.has_attr("href") else None
        except Exception:
            url = None

        # Dates (try machine-readable first)
        start_s = (card.get("data-cg-event-start")
                   or (card.select_one("[itemprop='startDate']") or {}).get("content"))
        end_s = (card.get("data-cg-event-end")
                 or (card.select_one("[itemprop='endDate']") or {}).get("content"))

        # Fallbacks from visible text
        if not start_s:
            start_s = (card.select_one(".date, time") or {}).get("datetime") or (
                card.select_one("time") or {}).get("content")
        if not end_s:
            end_s = (card.select_one("time[datetime] + time") or {}).get("datetime")

        start = _parse_dt(start_s)
        end = _parse_dt(end_s)

        try:
            loc_el = card.select_one(".location, [itemprop='location'], .event-location")
            location = loc_el.get_text(" ", strip=True) if loc_el else None
        except Exception:
            location = None

        try:
            desc_el = card.select_one(".description, .event-description, [itemprop='description']")
            description = desc_el.get_text("\n", strip=True) if desc_el else None
        except Exception:
            description = None

        # Minimal validation
        if not title:
            warnings.append("Skipped an event with no title (template drift?).")
            continue

        events.append(Event(title=title, start=start, end=end, location=location, url=url, description=description))

        if limit and len(events) >= limit:
            break

    return events, warnings

# -------- CLI --------
def _cli(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Scrape GrowthZone events defensively.")
    p.add_argument("url", help="Calendar URL (GrowthZone-based)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = p.parse_args(argv)

    evs, warns = fetch_events(args.url, limit=args.limit)
    for w in warns:
        LOG.warning("WARN: %s", w)

    if args.json:
        print(json.dumps([e.as_dict() for e in evs], indent=2, ensure_ascii=False))
    else:
        for e in evs:
            print(f"- {e.title} @ {e.start or 'TBD'} -> {e.url or ''}")
    return 0

if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
