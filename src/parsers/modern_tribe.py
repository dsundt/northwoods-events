from __future__ import annotations

from typing import List, Dict, Any, Optional
from dataclasses import asdict

from bs4 import BeautifulSoup, Tag

# Local helpers
from utils.dates import looks_like_datetime, try_parse_datetime_range
from utils.text import _text  # assuming you have a tiny _text(html_or_node) helper; else inline

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Robust Modern Tribe (The Events Calendar) parser.
    Skips header/crumb blocks like 'Events' that contain no actual dates.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    items: List[Dict[str, Any]] = []

    # TEC list entries commonly appear as <article class="tribe-events-calendar-list__event"> ...</article>
    # but sites vary. Fall back to anything with an event permalink pattern.
    candidates: List[Tag] = []
    candidates.extend(soup.select("article.tribe-events-calendar-list__event"))
    candidates.extend(soup.select("div.tribe-events-calendar-list__event"))
    # Fallbacks for older TEC themes:
    if not candidates:
        candidates = soup.select("article, div")

    for node in candidates:
        # Find a permalink-ish anchor
        a = node.find("a", href=True)
        if not a or "/event" not in (a["href"] or ""):
            continue

        title = _text(a)
        if not title:
            # try inner headings
            h = node.find(["h3", "h2", "h4"])
            title = _text(h) if h else ""

        # locate a block with date/time-ish text near this node
        dt_block: Optional[Tag] = None
        # Common TEC selectors
        for sel in [
            ".tribe-events-calendar-list__event-date",
            ".tribe-events-schedule",
            "time",
            ".tribe-event-date-start",
            ".tribe-event-date",
        ]:
            dt_block = node.select_one(sel)
            if dt_block:
                break
        if dt_block is None:
            # look at small text blocks around the link
            dt_block = (a.find_parent().find_next("time") if a.find_parent() else None) or node.find("time")

        if not dt_block:
            # no time/date available; skip to avoid bad guesses
            continue

        raw_dt_text = _text(dt_block)
        # Guard: skip junk like plain 'Events' or other nav labels
        if not looks_like_datetime(raw_dt_text):
            continue

        dt_range = try_parse_datetime_range(raw_dt_text)
        if not dt_range:
            # still couldn't parse; skip safely
            continue

        start, end = dt_range

        item: Dict[str, Any] = {
            "title": title,
            "start": start,
            "end": end,
            "location": _nearest_location_text(node),
            "url": a["href"],
        }
        items.append(item)

    return items

def _nearest_location_text(node: Tag) -> str:
    # TEC often uses these classes; otherwise, grab a small-detail block
    for sel in [".tribe-events-calendar-list__event-venue", ".tribe-venue", ".tribe-events-venue-details"]:
        v = node.select_one(sel)
        if v:
            return _text(v)
    # fallback: short trailing text
    tail = node.find(["p", "span", "div"])
    return _text(tail) if tail else ""
