from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

__all__ = ["parse_municipal"]

MONTH_TOKEN = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)(?:[a-z]{0,6})\b"


def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""


def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Generic municipal WordPress calendar parser.
    Tolerates list views, block editor layouts, and simple tables.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Common patterns: list of posts with dates, or a table with rows.
    # 1) Articles / posts
    posts = soup.select("article, .wp-block-post, .event, .calendar-item")
    if not posts:
        # 2) Table rows
        posts = soup.select("table tr")

    for p in posts:
        a = p.find("a", href=True)
        if not a:
            continue

        title = _text(p.find(["h2", "h3"])) or _text(a)
        title = re.sub(r"\s+", " ", (title or "")).strip()
        if not title or title.lower() in {"events", "calendar"}:
            continue

        # Date candidates
        dt = ""
        time_tag = p.find("time")
        if time_tag and time_tag.has_attr("datetime"):
            dt = time_tag["datetime"]
        elif time_tag:
            dt = _text(time_tag)

        if not dt:
            # try any cell/span with 'date' in class
            cand = p.find(class_=re.compile("date|time", re.I))
            dt = _text(cand)

        if not dt:
            # scan text of the row/block
            dt = _text(p)

        if not re.search(MONTH_TOKEN, dt, re.I) and not (time_tag and time_tag.has_attr("datetime")):
            # skip rows without any date-like token
            continue

        url = urljoin(base_url, a["href"])
        location = ""
        loc_el = p.find(class_=re.compile("location|venue|where", re.I))
        if loc_el:
            location = _text(loc_el)

        items.append({"title": title, "start": dt.strip(), "url": url, "location": location})

    return items
