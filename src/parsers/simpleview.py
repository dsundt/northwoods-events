# src/parsers/simpleview.py
from __future__ import annotations
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from ..models import Event
from ..utils.dates import parse_datetime_range

def _text(n): return " ".join(n.get_text(" ", strip=True).split()) if n else ""

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    for c in soup.select("[data-result], .event, .cards .card"):
        title_node = c.select_one("h3 a, .card-title a, a[href]")
        title = _text(title_node) if title_node else "Untitled"
        url = title_node["href"] if title_node and title_node.has_attr("href") else base_url
        dt_block = c.select_one(".date, .event-date, time")
        dt_text = _text(dt_block or c)
        start, end = parse_datetime_range(dt_text)

        venue = c.select_one(".venue, .location, [itemprop='location']")
        desc  = c.select_one(".summary, .description, [itemprop='description']")

        out.append(Event(
            title=title,
            start=start,
            end=end,
            url=url,
            location=_text(venue) if venue else None,
            description=_text(desc) if desc else None,
        ).__dict__)
    return out
