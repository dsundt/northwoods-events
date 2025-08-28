# src/parsers/municipal.py
from __future__ import annotations
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from ..models import Event
from ..utils.dates import parse_datetime_range

def _text(n): return " ".join(n.get_text(" ", strip=True).split()) if n else ""

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    # Very loose selectors to handle common WP calendar widgets
    for row in soup.select(".calendar, .events, .list, article, li"):
        title_node = row.select_one("a, h3, h2, .event-title")
        if not title_node: 
            continue
        title = _text(title_node)
        url = title_node["href"] if title_node.has_attr("href") else base_url

        dt_node = row.select_one("time, .date, .event-date, .when")
        dt_text = _text(dt_node or row)
        start, end = parse_datetime_range(dt_text)

        venue = row.select_one(".location, .venue, .where")
        desc  = row.select_one(".description, .summary, p")

        out.append(Event(
            title=title,
            start=start,
            end=end,
            url=url,
            location=_text(venue) if venue else None,
            description=_text(desc) if desc else None,
        ).__dict__)
    return out
