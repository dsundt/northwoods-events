from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

__all__ = ["parse_simpleview"]

MONTH_TOKEN = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)(?:[a-z]{0,6})\b"


def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""


def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Simpleview sites vary a lot; parse card/list patterns and pull title/date/url.
    We pass through the date text (normalize upstream if needed).
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Common card/list selectors across Simpleview builds
    cards = soup.select(
        ".event, .event-card, .event-list-item, .card, .listing, article, li"
    )

    for c in cards:
        a = c.find("a", href=True)
        if not a:
            continue

        # Title
        title = _text(c.find(["h3", "h2"])) or _text(a)
        title = re.sub(r"\s+", " ", (title or "")).strip()
        if not title or title.lower() in {"events", "calendar"}:
            continue

        # Date text
        dt = ""
        for sel in ["time", ".date", ".event-date", ".dates", ".event__date"]:
            el = c.select_one(sel)
            if el:
                if el.name == "time" and el.has_attr("datetime"):
                    dt = el["datetime"]
                else:
                    dt = _text(el)
                break
        if not dt:
            dt = _text(c)

        if not re.search(MONTH_TOKEN, dt, re.I) and not (c.find("time") and c.find("time").has_attr("datetime")):
            # likely a non-event listing card; skip
            continue

        url = urljoin(base_url, a["href"])
        location = ""
        loc_el = c.find(class_=re.compile("location|venue|where", re.I))
        if loc_el:
            location = _text(loc_el)

        items.append({"title": title, "start": dt.strip(), "url": url, "location": location})

    return items
