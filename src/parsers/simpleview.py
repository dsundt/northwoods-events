from __future__ import annotations

from typing import List, Dict, Any
from bs4 import BeautifulSoup

from parsers._text import text as _text
from models import Event
from utils.dates import parse_datetime_range


def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    for c in soup.select("[data-result], .event, .cards .card, article"):
        title_node = c.select_one("h3 a, .card-title a, a[href]")
        title = _text(title_node) or "Untitled"
        url = title_node["href"] if title_node and title_node.has_attr("href") else base_url

        dt_block = c.select_one(".date, .event-date, time") or c
        start, end = parse_datetime_range(_text(dt_block))

        venue = c.select_one(".venue, .location, [itemprop='location']")
        desc  = c.select_one(".summary, .description, [itemprop='description']")

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
