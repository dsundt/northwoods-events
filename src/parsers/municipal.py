from __future__ import annotations

from typing import List, Dict, Any
from bs4 import BeautifulSoup

from models import Event
from utils.dates import parse_datetime_range
from parsers._text import text as _text


def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    # Very loose selectors to accommodate common WP calendars
    for row in soup.select(".calendar *, .events *, .list *, article, li"):
        title_node = row.select_one("a, h3, h2, .event-title")
        if not title_node:
            continue

        title = _text(title_node) or "Untitled"
        url = title_node["href"] if title_node.has_attr("href") else base_url

        dt_node = row.select_one("time, .date, .event-date, .when") or row
        start, end = parse_datetime_range(_text(dt_node))

        venue = row.select_one(".location, .venue, .where")
        desc  = row.select_one(".description, .summary, p")

        out.append(
            Event(
                title=title,
                start=start,
                end=end,
                url=url,
                location=_text(venue) or None,
                description=_text(desc) or None,
            ).__dict__
        )
    return out
