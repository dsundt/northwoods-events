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

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    for row in soup.select(".calendar *, .events *, .list *, article, li"):
        title_node = row.select_one("a, h3, h2, .event-title")
        if not title_node:
            continue
        title = (_text(title_node) or "Untitled").strip()
        url = title_node["href"] if title_node.has_attr("href") else base_url

        times = row.select("time[datetime]")
        start = end = None
        if times:
            try:
                start = parse_iso_or_text(times[0]["datetime"])
                end = parse_iso_or_text(times[1]["datetime"]) if len(times) > 1 else start
            except Exception:
                start = end = None

        if start is None:
            dt_node = row.select_one("time, .date, .event-date, .when") or row
            maybe = try_parse_datetime_range(_text(dt_node))
            if not maybe:
                continue
            start, end = maybe

        venue = row.select_one(".location, .venue, .where")
        desc  = row.select_one(".description, .summary, p")

        out.append(Event(
            title=title,
            start=start,
            end=end,
            url=url,
            location=_text(venue) or None,
            description=_text(desc) or None,
        ).__dict__)

    return out
