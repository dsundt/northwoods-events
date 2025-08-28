from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from utils.dates import parse_datetime_range

__all__ = ["parse_simpleview"]


# ---------------------------
# Helpers
# ---------------------------

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""


_DEFUSE_HEADERS = {"events", "upcoming events", "featured events", "festivals & events"}

# Common places Simpleview sites put date/time
_DATE_HINTS = (
    ".event-date",
    ".event__date",
    ".eventDate",
    ".event_item_date",
    ".listing__date",
    ".card-date",
    "time",
)

# Common event card containers on Simpleview builds
_CARD_SELECTORS = (
    "article.event",
    "article.listing",
    "li.listing",
    "li.event",
    "div.event",
    "div.card--event",
    "div.listing__item",
    "div.sv-event",
    "li.grid__item",
)


def _maybe_parse(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s or s.lower() in _DEFUSE_HEADERS:
        return None
    try:
        return parse_datetime_range(s)
    except Exception:
        return None


# ---------------------------
# Parser
# ---------------------------

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Tolerant Simpleview parser.

    Handles a variety of card/list layouts found on DMO sites using Simpleview.
    We try focused selectors first; if nothing is found, fall back to any node with a link
    that *looks* like an event and contains a date-ish snippet nearby.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # 1) Try known card containers
    cards = []
    for sel in _CARD_SELECTORS:
        cards.extend(soup.select(sel))
    # De-dup while preserving order
    seen = set()
    cards = [c for c in cards if id(c) not in seen and not seen.add(id(c))]

    # 2) Fallback: any container with a link whose href hints "event"
    if not cards:
        maybe = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if any(x in href for x in ("/event", "/events", "event=")):
                maybe.append(a.find_parent(["article", "li", "div"]) or a)
        cards = maybe

    for c in cards:
        a = c.find("a", href=True)
        title = _text(c.find(["h3", "h2"])) or (a and _text(a)) or ""
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            # Some builds use figcaption or .listing__title
            title = _text(c.select_one("figcaption, .listing__title, .card-title"))
            title = re.sub(r"\s+", " ", title or "").strip()
        if not title:
            continue

        # Find date/time text: prefer explicit elements
        dt_text = ""
        for hint in _DATE_HINTS:
            el = c.select_one(hint)
            if el:
                # Some sites put date parts in separate spans; grab them all
                dt_text = _text(el)
                if dt_text:
                    break
        if not dt_text:
            # Heuristic: look for small/metadata lines
            dt_text = _text(c.select_one(".meta, .listing__meta, .card-meta"))

        # Final fallback: the whole card text (but filter out obvious headings)
        if not dt_text or dt_text.lower() in _DEFUSE_HEADERS:
            dt_text = _text(c)

        start_iso = (
            _maybe_parse(dt_text)
            or _maybe_parse(title)  # titles sometimes include "Oct 4–5"
            or None
        )
        if not start_iso:
            # Skip containers that don't actually represent events
            continue

        url = urljoin(base_url, a["href"]) if a else base_url

        # Location: try common selectors
        location = ""
        loc_el = (
            c.select_one(".event-location")
            or c.select_one(".location")
            or c.select_one(".listing__location")
            or c.select_one(".card-location")
        )
        if loc_el:
            location = _text(loc_el).strip()

        items.append(
            {
                "title": title,
                "start": start_iso,
                "url": url,
                "location": location,
            }
        )

    return items
