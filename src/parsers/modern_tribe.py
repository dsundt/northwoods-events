# src/parsers/modern_tribe.py
from __future__ import annotations
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from ._text import text as _text  # or inline a small helper to get text
from ..models import Event
from ..utils.dates import parse_datetime_range

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    for card in soup.select("[data-event], .tribe-events-calendar-list__event"):
        title_node = card.select_one("h3, .tribe-events-calendar-list__event-title")
        url_node = card.select_one("a[href]")
        dt_block = card.select_one("time, .tribe-events-calendar-list__event-datetime, .tribe-event-date-start")
        where = card.select_one(".tribe-events-calendar-list__event-venue, .tribe-venue, .venue, .location")
        desc = card.select_one(".tribe-events-calendar-list__event-description, .description, .tribe-events-list-event-description")

        title = _text(title_node) if title_node else "Untitled"
        url = url_node["href"] if url_node and url_node.has_attr("href") else base_url
        dt_text = _text(dt_block) if dt_block else ""
        start, end = parse_datetime_range(dt_text)  # always two values now

        event = Event(
            title=title.strip(),
            start=start,
            end=end,
            url=url,
            location=_text(where).strip() if where else None,
            description=_text(desc).strip() if desc else None,
        )
        out.append(event.__dict__)
    return out
