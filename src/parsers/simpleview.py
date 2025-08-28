from __future__ import annotations
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import re
from datetime import datetime

__all__ = ["parse_simpleview"]

# Simpleview pages can be pure landing pages (no server-rendered events).
# Only collect from specific containers that actually hold event list/cards.
_EVENT_WRAPPERS = [
    "[data-sv-search-results] .result",     # SV search/listing widget
    ".sv-event-list .sv-event",             # common pattern
    ".event-cards .card",                    # generic card grids
    ".collection .card",                     # site-specific collections
    ".events .card", ".events-list .card",
]

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
DATE_INLINE = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:,\s*(\d{4}))?\b", re.I)

def _text(n) -> str:
    return " ".join(n.stripped_strings) if n else ""

def _infer_year(mon: int) -> int:
    today = datetime.today().date()
    y = today.year
    # If page looks like fall schedule and month already passed far, bump year (safe heuristic)
    if mon < today.month - 2:
        return y + 1
    return y

def _parse_inline_date(txt: str) -> str | None:
    m = DATE_INLINE.search(txt or "")
    if not m:
        return None
    mon = MONTHS[m.group(1).lower()]
    day = int(m.group(2))
    year = int(m.group(3)) if m.group(3) else _infer_year(mon)
    return datetime(year, mon, day).isoformat()

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # If the page has zero trusted wrappers, return [] — do NOT scrape page copy.
    blocks = []
    for sel in _EVENT_WRAPPERS:
        blocks.extend(soup.select(sel))

    if not blocks:
        # Try a very conservative fallback: cards/links that *look* like event entries
        # (title in heading + date snippet nearby) — otherwise return empty.
        conservative = []
        for card in soup.select(".card, article, li"):
            a = card.find("a", href=True)
            if not a:
                continue
            title = _text(card.find(["h3","h2"]) or a).strip()
            if not title:
                continue
            # Needs a date mention inside the card
            if not _parse_inline_date(_text(card)):
                continue
            conservative.append(card)
        blocks = conservative

    seen = set()
    for b in blocks:
        a = b.find("a", href=True)
        if not a:
            continue
        url = urljoin(base_url, a["href"])
        if url in seen:
            continue
        seen.add(url)

        title = _text(b.find(["h3","h2"]) or a).strip()
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # Start date — attempt inline date within the same block
        start = _parse_inline_date(_text(b))
        if not start:
            # Skip (prevents pulling marketing/guide pages like Oneida’s overview)
            continue

        # Location (best-effort)
        location = ""
        loc = b.find(class_=re.compile(r"(venue|location)", re.I))
        if loc:
            location = _text(loc)

        items.append({"title": title, "start": start, "url": url, "location": location})

    return items
