from __future__ import annotations
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

from utils.fetchers import fetch_rendered

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _looks_like_event_href(href: str) -> bool:
    if not href:
        return False
    h = href.lower()
    # Heuristics for Simpleview event detail pages:
    return ("/event/" in h) or ("/events/" in h and re.search(r"/\w", h)) or ("?event=" in h)

def _parse_simpleview_from_html(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Typical card containers on Simpleview sites:
    candidates = soup.select(
        ".event, .event-item, .listing, .teaser, .card, li, article"
    )

    seen = set()
    for block in candidates:
        a = block.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "")
        if not _looks_like_event_href(href):
            continue

        title = _text(block.find(["h2", "h3"]) or a).strip()
        if not title:
            continue

        # Avoid nav / duplicates
        key = (title, href)
        if key in seen:
            continue
        seen.add(key)

        # Try to find a date/time nearby
        date_el = block.find("time") or block.find(class_=re.compile("date|time", re.I))
        date_text = _text(date_el).strip()

        items.append({
            "title": title,
            "start": date_text,   # leave as text (consistent with Simpleview; upstream can parse if needed)
            "url": urljoin(base_url, href),
            "location": ""
        })

    return items

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Parse a Simpleview page. If static HTML has no events (common), we fallback
    to a rendered fetch via Playwright and re-parse.
    """
    # First pass: static HTML
    items = _parse_simpleview_from_html(html, base_url)
    if items:
        return items

    # Fallback: JS-rendered content
    rendered = fetch_rendered(base_url, wait_selector="a")
    if not rendered:
        return []

    return _parse_simpleview_from_html(rendered, base_url)
