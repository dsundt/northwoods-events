from __future__ import annotations
import re
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.dates import parse_datetime_range

__all__ = ["parse_st_germain_ajax"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Their site renders three static cards server-side (even though it's called 'AJAX').
    We only take anchors within the event list/cards and parse a single clean line for the date.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Find likely event cards: main content links under /events/
    anchors = [a for a in soup.find_all("a", href=True) if "/events/" in a["href"]]
    seen = set()
    for a in anchors:
        url = urljoin(base_url, a["href"])
        if url in seen:
            continue
        seen.add(url)

        # Title: just the anchor text (no concatenation of siblings)
        title = _text(a).strip()
        if not title:
            continue

        # Look near the link for a line like "Monday, September 20th, 2025" etc.
        container = a.find_parent(["article", "div", "li"]) or a
        blob = _text(container)
        # Grab the first date-looking fragment (month word + day + optional year)
        m = re.search(r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?", blob, flags=re.I)
        start = None
        if m:
            # remove ordinal suffixes like "20th"
            frag = re.sub(r"(\d)(st|nd|rd|th)", r"\1", m.group(0))
            try:
                start = parse_datetime_range(frag)
            except Exception:
                start = None
        if not start:
            # as a fallback try the title itself
            try:
                start = parse_datetime_range(title)
            except Exception:
                continue  # skip if we can't get a date

        items.append({"title": title, "start": start, "url": url, "location": ""})

    return items
