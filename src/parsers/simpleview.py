#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Defensive Simpleview events scraper (drop-in).
Shared pattern with retries, timeouts, guarded parsing, and stable schema.
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
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger("simpleview")
if not LOG.handlers:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [simpleview] %(message)s"))
    LOG.addHandler(h)
LOG.setLevel(logging.INFO)

DEFAULT_TIMEOUT = (6.1, 20.0)
MAX_RETRIES = 5
BACKOFF_FACTOR = 0.6
STATUS_FORCELIST = (429, 500, 502, 503, 504)
ALLOWED_DOMAINS = ("visitsimpleview", "simpleviewinc", "visittheusa", "visit", "events")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
]

@dataclasses.dataclass
class Event:
    title: str
    start: Optional[dt.datetime]
    end: Optional[dt.datetime]
    location: Optional[str]
    url: Optional[str]
    description: Optional[str] = None
    source: str = "simpleview"

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

_ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?")

def _parse_dt(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    s = s.strip()
    try:
        if _ISO.match(s):
            return dt.datetime.fromisoformat(s.replace(" ", "T"))
        # common Simpleview markup: <meta itemprop="startDate" content="2025-07-04T19:00">
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None

def fetch_events(calendar_url: str, limit: Optional[int] = None) -> Tuple[List[Event], List[str]]:
    warnings: List[str] = []
    events: List[Event] = []

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
        if not resp.text:
            return [], warnings

    soup = BeautifulSoup(resp.text, "html.parser")

    # Simpleview often uses schema.org Event cards and list/grid items
    cards = soup.select("[itemtype*='schema.org/Event'], article.event, .event-card, .sv-event")
    if not cards:
        warnings.append("No event cards found; using generic article/li fallback.")
        cards = soup.select("article, li.event, .event")[:200]

    for card in cards:
        # Title
        try:
            title_el = card.select_one("[itemprop='name'], .event-title, h3, h2, a")
            title = title_el.get_text(strip=True) if title_el else ""
        except Exception:
            title = ""

        # URL
        try:
            url_el = card.select_one("[itemprop='url'], a[href*='event']")
            url = url_el["href"].strip() if url_el and url_el.has_attr("href") else None
        except Exception:
            url = None

        # Dates (prefer machine-readable)
        start_s = (card.select_one("[itemprop='startDate']") or {}).get("content") or (
            card.select_one("time[datetime]") or {}
        ).get("datetime")
        end_s = (card.select_one("[itemprop='endDate']") or {}).get("content") or (
            card.select_one("time[datetime] + time") or {}
        ).get("datetime")

        start = _parse_dt(start_s)
        end = _parse_dt(end_s)

        # Location
        try:
            loc_el = card.select_one("[itemprop='location'], .event-location, .sv-location")
            location = loc_el.get_text(" ", strip=True) if loc_el else None
        except Exception:
            location = None

        # Description
        try:
            desc_el = card.select_one("[itemprop='description'], .event-description, .sv-description")
            description = desc_el.get_text("\n", strip=True) if desc_el else None
        except Exception:
            description = None

        if not title:
            warnings.append("Skipped one card without a title (template drift?)")
            continue

        events.append(Event(title=title, start=start, end=end, location=location, url=url, description=description))
        if limit and len(events) >= limit:
            break

    return events, warnings

def _cli(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Scrape Simpleview events defensively.")
    p.add_argument("url", help="Calendar URL (Simpleview-powered)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--json", action="store_true")
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
