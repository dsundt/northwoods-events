# src/parsers/growthzone.py
from __future__ import annotations
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from ..models import Event
from ..utils.dates import parse_datetime_range

def _text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    for a in soup.select("a[href*='events/details'], a[href*='events/details/']"):
        parent = a.find_parent()
        title = _text(a)
        dt_node = parent.find(string=True) if parent else a
        dt_text = _text(parent or a)
        start, end = parse_datetime_range(dt_text)

        event = Event(
            title=title,
            start=start,
            end=end,
            url=a["href"],
            location=None,
            description=None,
        )
        out.append(event.__dict__)
    return out
