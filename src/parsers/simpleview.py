from __future__ import annotations
import re
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.dates import parse_datetime_range

__all__ = ["parse_simpleview"]

EVENT_HREF_PAT = re.compile(r"/events?/(?:details|.+)", re.I)

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _looks_like_event_block(node) -> bool:
    txt = _text(node).lower()
    # avoid menus/headers; require at least one date-ish token
    has_month = re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", txt)
    # and a number (day)
    has_day = re.search(r"\b\d{1,2}\b", txt)
    return bool(has_month and has_day)

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Simpleview pages are often client-rendered; be conservative:
    - Only pick anchors that look like event detail pages OR
    - Blocks that look like event cards (month/day present).
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    anchors = [a for a in soup.find_all("a", href=True) if EVENT_HREF_PAT.search(a["href"])]
    if not anchors:
        # As a fallback, look for "card" style blocks with dates and an inner link
        cards = [c for c in soup.select("article, .card, .event, .tile, li") if _looks_like_event_block(c)]
        anchors = []
        for c in cards:
            a = c.find("a", href=True)
            if a:
                anchors.append(a)

    seen = set()
    for a in anchors:
        url = urljoin(base_url, a["href"])
        if url in seen:
            continue
        seen.add(url)

        block = a.find_parent(["article", "div", "li"]) or a
        title = _text(block.find(["h3", "h2"])) or _text(a)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # date text: search the block (never the whole page)
        blob = _text(block)
        # find first month token fragment
        m = re.search(r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?(?:\s*@\s*\d{1,2}:\d{2}\s*(?:am|pm))?", blob, flags=re.I)
        if not m:
            # skip if we can’t confidently locate a date near the anchor
            continue
        try:
            start = parse_datetime_range(m.group(0))
        except Exception:
            continue

        items.append({"title": title, "start": start, "url": url, "location": ""})

    return items
