from __future__ import annotations
import os, sys
_PARSERS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_PARSERS_DIR)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from typing import List, Dict, Any
from bs4 import BeautifulSoup

from parsers._text import text as _text
from models import Event
from utils.dates import try_parse_datetime_range, parse_iso_or_text

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    cards = soup.select(
        "[data-event], .tribe-events-calendar-list__event, .tribe-events-list-event"
    )

    for card in cards:
        title_node = card.select_one("h3 a, .tribe-events-calendar-list__event-title a, h3, .tribe-events-list-event-title a")
        url = title_node["href"] if title_node and title_node.has_attr("href") else base_url
        title = (_text(title_node) or "Untitled").strip()

        # 1) Prefer machine-readable <time datetime="...">
        times = card.select("time[datetime]")
        start = end = None
        if times:
            try:
                start = parse_iso_or_text(times[0]["datetime"])
                end = parse_iso_or_text(times[1]["datetime"]) if len(times) > 1 else start
            except Exception:
                start = end = None

        # 2) Fallback to free-text block if needed
        if start is None:
            dt_block = card.select_one(
                ".tribe-events-calendar-list__event-datetime, .tribe-event-date-start, .tribe-events-schedule, time"
            ) or card
            maybe = try_parse_datetime_range(_text(dt_block))
            if not maybe:
                continue  # skip undated cards
            start, end = maybe

        venue = card.select_one(
            ".tribe-events-calendar-list__event-venue, .tribe-venue, .venue, .location"
        )
        desc = card.select_one(
            ".tribe-events-calendar-list__event-description, "
            ".tribe-events-list-event-description, .description, .summary"
        )

        out.append(Event(
            title=title,
            start=start,
            end=end,
            url=url,
            location=_text(venue) or None,
            description=_text(desc) or None,
        ).__dict__)

    return out
