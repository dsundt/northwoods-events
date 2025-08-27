from __future__ import annotations

import re
from bs4 import BeautifulSoup
from typing import Iterable, Dict, Any
from .utils import absolutize
from ..normalize import parse_datetime_range, clean_text

DATE_RE = re.compile(r"[A-Za-z]{3,9}\s+\d{1,2}(,\s*\d{4})?(\s*@\s*|\s+)\d{1,2}(:\d{2})?\s*(am|pm)?", re.I)

def parse(html: str, base_url: str) -> Iterable[Dict[str, Any]]:
    """
    Simpleview events list parser (used by many DMO sites like Minocqua, Oneida).
    Targets common card/list patterns.
    """
    soup = BeautifulSoup(html, "lxml")

    # Common selectors seen on Simpleview sites
    cards = []
    cards.extend(soup.select(".event-item, .sv-event, .listing, .v-calendar__event"))
    cards.extend(soup.select("article.event, li.event"))

    # Fallback: links that look like /event/... or contain "events/"
    if not cards:
        for a in soup.select("a[href]"):
            href = a["href"]
            if "/event" in href or "/events/" in href:
                cards.append(a.parent)

    seen = set()
    for c in cards:
        # Anchor + title
        a = c.select_one("a[href*='/event']") or c.select_one("a[href*='/events/']") or c.select_one("a")
        if not a or not a.has_attr("href"):
            continue
        url = absolutize(base_url, a["href"])
        title = clean_text(a.get_text(" ", strip=True))
        if not title:
            # Sometimes title lives in a heading sibling
            h = c.select_one("h2, h3")
            title = clean_text(h.get_text(" ", strip=True)) if h else title

        # Skip duplicates
        key = (title, url)
        if key in seen:
            continue
        seen.add(key)

        # Date text — try a few nearby containers
        date_text = ""
        for sel in [".date", ".event-date", ".sv-date", ".event__date", ".card-date"]:
            el = c.select_one(sel)
            if el:
                date_text = clean_text(el.get_text(" ", strip=True))
                break
        if not date_text:
            # Look around the card for a readable date pattern
            txt = clean_text(c.get_text(" ", strip=True))
            m = DATE_RE.search(txt)
            if m:
                date_text = m.group(0)

        start_dt, end_dt, all_day = parse_datetime_range(
            date_text=date_text,
            tzname="America/Chicago",
        )

        # Location (best-effort)
        location = ""
        for sel in [".venue", ".location", ".event-venue", ".sv-venue"]:
            el = c.select_one(sel)
            if el:
                location = clean_text(el.get_text(" ", strip=True))
                break

        # Only accept cards with a real title and a non-list URL
        if title and not url.rstrip("/").endswith("/events/"):
            yield {
                "title": title,
                "url": url,
                "location": location,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "all_day": all_day,
            }
