from __future__ import annotations

from typing import List, Dict, Any
from bs4 import BeautifulSoup

from parsers._text import text as _text
from models import Event
from utils.dates import parse_datetime_range


def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    # GrowthZone calendar/detail links tend to match this
    for a in soup.select("a[href*='events/details'], a[href*='events/details/']"):
        parent = a.find_parent() or a
        title = _text(a) or "Untitled"
        url = a["href"] if a.has_attr("href") else base_url

        start, end = parse_datetime_range(_text(parent))

        out.append(
            Event(
                title=title,
                start=start,
                end=end,
                url=url,
                location=None,
                description=None,
            ).__dict__
        )

    return out
