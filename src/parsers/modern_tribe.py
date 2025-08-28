from __future__ import annotations
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils.dates import parse_datetime_range

__all__ = ["parse_modern_tribe"]

# Helpers
def _text(node) -> str:
    return " ".join(node.stripped_strings) if node else ""

# Containers/classes we trust for individual events across MT versions
_EVENT_SELECTORS = [
    "article.tribe-events-calendar-list__event",
    "div.tribe-events-calendar-list__event",
    "div.tribe-common-g-row",                    # legacy list rows
    "li.tribe-events-list-event",                # very old
    "div.tribe-events-event-card",               # card variant
]

# Things that are *not* events (page headers, section headings)
_DEFUSE = {"events", "upcoming events", "featured events", "view calendar", "view downtown events"}

def _best_title(card) -> str:
    # Prefer the inner event title element, fall back to the first anchor/heading
    for sel in (".tribe-events-calendar-list__event-title",
                ".tribe-events-event-card__title",
                "h3", "h2", "a[rel='bookmark']", "a"):
        el = card.select_one(sel)
        if el and (t := _text(el)).strip():
            return re.sub(r"\s+", " ", t).strip()
    return ""

def _find_dt_text(card) -> Optional[str]:
    # Prefer explicit date/time blocks; otherwise use a trimmed card text minus obvious headings
    for sel in (".tribe-event-date-start", ".tribe-event-date",
                ".tribe-events-calendar-list__event-datetime",
                "time", ".tribe-events-event-datetime"):
        el = card.select_one(sel)
        if el:
            txt = _text(el).strip()
            if txt and txt.lower() not in _DEFUSE:
                return txt
    # fallback: card text without navigation/buttons
    txt = _text(card).strip()
    if not txt or txt.lower() in _DEFUSE:
        return None
    return txt

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    cards = []
    for sel in _EVENT_SELECTORS:
        cards.extend(soup.select(sel))
    # De-dup
    seen = set()
    uniq_cards = []
    for c in cards:
        if id(c) in seen:
            continue
        seen.add(id(c))
        uniq_cards.append(c)

    for c in uniq_cards:
        title = _best_title(c)
        if not title:
            continue

        # Date/time (always run through parser to guarantee ISO, never keep raw fragments like "10:00 am")
        start_iso: Optional[str] = None
        dt_text = _find_dt_text(c)

        # Try datetime in the dedicated block, then in the title (handles things like "October 4 - October 5")
        for candidate in (dt_text, title):
            if not candidate:
                continue
            try:
                start_iso = parse_datetime_range(candidate)
                break
            except Exception:
                continue
        if not start_iso:
            # Not an actual event card (or no date visible)
            continue

        a = c.find("a", href=True)
        url = urljoin(base_url, a["href"]) if a else base_url

        # location (best-effort)
        location = ""
        loc = c.find(class_=re.compile(r"(venue|location)", re.I))
        if loc:
            location = _text(loc)

        items.append({
            "title": title,
            "start": start_iso,
            "url": url,
            "location": location,
        })
    return items
