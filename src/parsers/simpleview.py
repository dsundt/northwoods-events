from __future__ import annotations
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils.dates import combine_date_and_time

__all__ = ["parse_simpleview"]

# Only pull from structured result containers; ignore overview pages & headers.
RESULT_CONTAINERS = (
    "#results, .results, .results-list, .event-results, "
    ".events-list, .event-list, .sv-results, "
    ".contentRender_name_plugins_events_layout_list .results"
)

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _first_datetime(candidate) -> str | None:
    t = candidate.find("time", attrs={"datetime": True})
    if not t:
        return None
    date_attr = t.get("datetime", "").split("T")[0]
    time_text = t.get_text(" ", strip=True)
    return combine_date_and_time(date_attr, time_text)

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    containers = soup.select(RESULT_CONTAINERS)
    if not containers:
        # Some Simpleview templates mark each “tile” with a data-entity-id
        containers = soup.select("[data-entity-id]")
    if not containers:
        return items  # Don’t scrape headers/hero links

    # Events usually appear as list items or “card” divs inside these containers.
    cards = []
    for c in containers:
        cards.extend(c.select("li, .result, .card, .tile, article"))

    for card in cards:
        a = card.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "")
        # Only consider real event detail pages
        if "/event/" not in href:
            continue

        start_iso = _first_datetime(card)
        if not start_iso:
            # sometimes the <time> lives on a sibling
            sib = card.find_next_sibling()
            if sib:
                start_iso = _first_datetime(sib)

        title = _text(card.find(["h3", "h2"])) or a.get_text(strip=True)
        if not title:
            continue

        items.append({
            "title": title,
            "start": start_iso or "",  # Simpleview often omits time/date here; keep empty rather than wrong.
            "url": urljoin(base_url, href),
            "location": _text(card.find(class_=re.compile("location|venue", re.I))) or "",
        })

    return items
