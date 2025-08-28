from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils.dates import parse_datetime_range

__all__ = ["parse_modern_tribe"]

HEADER_WORDS = {"events", "featured events", "upcoming events"}

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _pick_title(card) -> str:
    # Prefer the event title element, then first anchor text
    for sel in [
        ".tribe-events-calendar-list__event-title",
        ".tribe-common-h7--min-medium",
        ".tribe-events-event-title",
        "h3", "h2"
    ]:
        el = card.select_one(sel)
        if el:
            t = _text(el)
            if t:
                return t
    a = card.find("a", href=True)
    return _text(a) if a else ""

def _pick_when(card) -> Optional[str]:
    # Prefer explicit date/time blocks; avoid feeding bare "Events" headers
    for sel in [
        ".tribe-events-calendar-list__event-date-tag",
        ".tribe-event-date-start",
        ".tribe-events-meta-group-details",
        ".tribe-common-b2",
        ".tribe-events-c-small-cta__date"  # newer skins
    ]:
        el = card.select_one(sel)
        if el:
            s = _text(el).strip()
            if s and s.lower() not in HEADER_WORDS:
                try:
                    return parse_datetime_range(s)
                except Exception:
                    pass
    # Fallback: try the card full text, then the title line
    s = _text(card)
    if s and s.lower() not in HEADER_WORDS:
        try:
            return parse_datetime_range(s)
        except Exception:
            pass
    t = _pick_title(card)
    if t:
        try:
            return parse_datetime_range(t)
        except Exception:
            pass
    return None

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    cards = soup.select(
        "article.tribe-events-calendar-list__event, "
        ".tribe-events-calendar-list__event, "
        ".tribe-events-event-card, "
        "article[type='tribe_events']"
    )
    if not cards:
        # Broad fallback – some sites render rows instead of <article>
        cards = soup.select(".tribe-common-g-row, .tribe-events-list-event")

    for c in cards:
        title = _pick_title(c)
        if not title:
            continue

        a = c.find("a", href=True)
        url = urljoin(base_url, a["href"]) if a else base_url

        start = _pick_when(c)
        if not start:
            # Skip container/section cards that aren’t real events
            continue

        loc = ""
        loc_el = c.find(class_=re.compile(r"(venue|location)", re.I))
        if loc_el:
            loc = _text(loc_el)

        items.append({"title": title, "start": start, "url": url, "location": loc})

    return items
