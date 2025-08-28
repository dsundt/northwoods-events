from __future__ import annotations

from typing import List, Dict, Any
from bs4 import BeautifulSoup

# ABSOLUTE imports (no leading dots)
from models import Event
from utils.dates import parse_datetime_range
from parsers._text import text as _text


def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Parse Modern Tribe / The Events Calendar list views.
    Returns a list of dicts (Event.__dict__).
    """
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    # Cover classic + modern list selectors
    cards = soup.select(
        "[data-event], .tribe-events-calendar-list__event, .tribe-events-list-event"
    )

    for card in cards:
        title_node = card.select_one("h3 a, .tribe-events-calendar-list__event-title a, h3, .tribe-events-list-event-title a")
        url = title_node["href"] if title_node and title_node.has_attr("href") else base_url
        title = _text(title_node) or "Untitled"

        # Common datetime containers
        dt_block = (
            card.select_one(
                "time, .tribe-events-calendar-list__event-datetime, "
                ".tribe-event-date-start, .tribe-events-schedule"
            )
            or card
        )
        start, end = parse_datetime_range(_text(dt_block))

        venue = card.select_one(
            ".tribe-events-calendar-list__event-venue, .tribe-venue, .venue, .location"
        )
        desc = card.select_one(
            ".tribe-events-calendar-list__event-description, "
            ".tribe-events-list-event-description, .description, .summary"
        )

        out.append(
            Event(
                title=title.strip(),
                start=start,
                end=end,
                url=url,
                location=_text(venue) or None,
                description=_text(desc) or None,
            ).__dict__
        )

    return out
