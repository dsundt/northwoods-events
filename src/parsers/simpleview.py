from __future__ import annotations
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

__all__ = ["parse_simpleview"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

EVENT_HINT = re.compile(r"(event)", re.I)

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Robust Simpleview parser:
    - Targets common Simpleview listing containers and cards.
    - Ignores hero/landing copy (e.g., Oneida County festivals page).
    - Emits only entries that look like event cards (have an <a> and an eventish wrapper).
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Simpleview cards frequently live under these containers:
    roots = soup.select(
        "[data-sv-listings], .sv-listings, .sv-listing-cards, .sv-event-list, "
        ".listingResults, .results, .card-grid"
    )
    if not roots:
        # Fall back to whole document (Minocqua renders fully on page)
        roots = [soup]

    cards = []
    for r in roots:
        cards.extend(r.select(
            # Common card wrappers and anchors
            "a.sv-event-card, .sv-event-card a, "
            ".listing a, .result a, "
            ".event a, .event-card a, "
            ".card a"
        ))

    # De-dup anchors that point to the same href
    seen = set()
    dedup: List[Any] = []
    for a in cards:
        href = a.get("href")
        if not href:
            continue
        key = urljoin(base_url, href)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(a)

    for a in dedup:
        url = urljoin(base_url, a["href"])
        # Make sure this anchor sits inside something that looks like an event card
        parent = a.find_parent(class_=EVENT_HINT) or a.find_parent(["article", "li", "div"])
        if not parent:
            continue

        title = _text(a)
        # Prefer an inner title element if present
        t_el = parent.select_one(".sv-event-card__title, .title, .event-title, h3, h2")
        if t_el and _text(t_el):
            title = _text(t_el)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # Simpleview listing often lacks full date/time on the list; emit URL + title only.
        # The pipeline can enrich by fetching detail if needed. Here we keep start empty when unknown.
        items.append({"title": title, "start": "", "url": url, "location": ""})

    # Heuristic: if we only found one giant block of text (landing page), return nothing.
    if len(items) <= 1 and not any("/event" in x["url"] or "/events/" in x["url"] for x in items):
        return []

    return items
