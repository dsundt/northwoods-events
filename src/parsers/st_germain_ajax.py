from __future__ import annotations
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils.dates import parse_datetime_range

__all__ = ["parse_st_germain_ajax"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    The listing page is AJAX-powered on the site, but our snapshot contains
    server-rendered featured cards linking to event pages. Use tight selectors
    so the title doesn't balloon and the start doesn't include full page text.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Look for obvious event tiles/cards (links to /events/<slug>/)
    anchors = [a for a in soup.find_all("a", href=True) if "/events/" in a["href"]]
    seen = set()

    for a in anchors:
        href = urljoin(base_url, a["href"])
        if href in seen:
            continue
        seen.add(href)

        card = a.find_parent(["article", "div", "li"]) or a
        title_el = a.find(["h2", "h3"]) or card.find(["h2", "h3"])
        title = _text(title_el) or _text(a)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # Try to harvest a concise date string from the same card (not entire page)
        date_el = None
        for sel in [".date", ".event-date", ".tribe-event-date-start", ".entry-meta", ".when"]:
            date_el = date_el or card.select_one(sel)
        date_txt = _text(date_el)

        start = ""
        if date_txt:
            try:
                start = parse_datetime_range(date_txt)
            except Exception:
                start = ""

        items.append({"title": title, "start": start, "url": href, "location": ""})

    return items
