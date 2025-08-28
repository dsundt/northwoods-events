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

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    for c in soup.select("[data-result], .event, .cards .card, article, li"):
        title_node = c.select_one("h3 a, .card-title a, a[href]")
        title = (_text(title_node) or "Untitled").strip()
        url = title_node["href"] if title_node and title_node.has_attr("href") else base_url

        times = c.select("time[datetime]")
        start = end = None
        if times:
            try:
                start = parse_iso_or_text(times[0]["datetime"])
                end = parse_iso_or_text(times[1]["datetime"]) if len(times) > 1 else start
            except Exception:
                start = end = None

        if start is None:
            dt_block = c.select_one(".date, .event-date, time") or c
            maybe = try_parse_datetime_range(_text(dt_block))
            if not maybe:
                continue
            start, end = maybe

        venue = c.select_one(".venue, .location, [itemprop='location']")
        desc  = c.select_one(".summary, .description, [itemprop='description']")

        out.append(Event(
            title=title,
            start=start,
            end=end,
            url=url,
            location=_text(venue) or None,
            description=_text(desc) or None,
        ).__dict__)

    return out
