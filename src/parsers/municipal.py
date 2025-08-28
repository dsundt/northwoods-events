from __future__ import annotations
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from utils.dates import parse_datetime_range

__all__ = ["parse_municipal"]

CAL_HINT = re.compile(r"(calendar|event)", re.I)

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Conservative municipal parser:
    - Only parse inside obvious calendar containers.
    - Require a parseable date near the title to avoid picking random links.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    containers = soup.find_all(True, class_=CAL_HINT) or soup.select("#calendar, .events, .ai1ec-calendar")
    if not containers:
        return []

    anchors = []
    for c in containers:
        anchors.extend(c.find_all("a", href=True))

    for a in anchors:
        title = _text(a)
        if not title or len(title) < 3:
            continue

        # Look around this row/card for a date line
        row = a.find_parent(["tr", "li", "article", "div"]) or a
        neighborhood = " ".join(filter(None, [_text(row), _text(row.find_next_sibling())]))[:500]
        start = ""
        try:
            start = parse_datetime_range(neighborhood)
        except Exception:
            continue  # if no credible date, skip this link

        items.append({
            "title": title.strip(),
            "start": start,
            "url": urljoin(base_url, a["href"]),
            "location": "",
        })

    return items
