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

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    for a in soup.select("a[href*='events/details'], a[href*='events/details/']"):
        parent = a.find_parent() or a
        title = (_text(a) or "Untitled").strip()
        url = a["href"] if a.has_attr("href") else base_url

        # Prefer nearby <time datetime>, else use parent text
        times = (parent or soup).select("time[datetime]")
        start = end = None
        if times:
            try:
                start = parse_iso_or_text(times[0]["datetime"])
                end = parse_iso_or_text(times[1]["datetime"]) if len(times) > 1 else start
            except Exception:
                start = end = None

        if start is None:
            maybe = try_parse_datetime_range(_text(parent))
            if not maybe:
                continue
            start, end = maybe

        out.append(Event(
            title=title,
            start=start,
            end=end,
            url=url,
            location=None,
            description=None,
        ).__dict__)
    return out
