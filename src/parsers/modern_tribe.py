from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from utils.dates import parse_datetime_range

__all__ = ["parse_modern_tribe"]


def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""


# Avoid feeding obvious headings into the date parser
_DEFUSE_HEADERS = {"events", "upcoming events", "featured events"}

# Common places where the date/time is stored
_TIME_CLASS_HINTS = (
    "time",
    "tribe-event-date-start",
    "tribe-event-date",
    "tribe-events-calendar-list__event-datetime",
    "tribe-events-event-datetime",
)


def _maybe_parse(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s or s.lower() in _DEFUSE_HEADERS:
        return None
    try:
        return parse_datetime_range(s)
    except Exception:
        return None


def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Tolerant Modern Tribe / The Events Calendar parser.
    Handles cases like:
      - "Events" headings
      - "August 30 @ 6:30 pm - 8:30 pm"
      - "October 4 - October 5"
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Modern Tribe often uses article cards; also fall back to common list layouts.
    cards = soup.select(
        "article, .tribe-events-calendar-list__event, .tribe-events-event-card, li.tribe-events-list-event"
    )
    if not cards:
        # last-chance: any element that has a link and some date-ish badge
        cards = [el for el in soup.find_all(True) if el.find("a", href=True)]

    for c in cards:
        a = c.find("a", href=True)
        title = _text(c.find(["h3", "h2"])) or _text(a)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # prefer explicit datetime blocks, otherwise use the card's text
        dt_text = ""
        for cls in _TIME_CLASS_HINTS:
            el = c.select_one(f".{cls}")
            if el:
                dt_text = _text(el)
                break
        if not dt_text:
            dt_text = _text(c)

        start_iso = (
            _maybe_parse(dt_text)
            or _maybe_parse(title)  # titles sometimes contain "Oct 4 - 5"
            or None
        )
        if not start_iso:
            # skip non-event containers (pure headings etc.)
            continue

        url = urljoin(base_url, a["href"]) if a else base_url

        location = ""
        loc_el = c.find(class_=re.compile(r"(location|venue)", re.I))
        if loc_el:
            location = _text(loc_el)

        items.append(
            {
                "title": title,
                "start": start_iso,
                "url": url,
                "location": location,
            }
        )

    return items
