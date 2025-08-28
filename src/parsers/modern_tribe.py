from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

__all__ = ["parse_modern_tribe"]

_BADGE_WORDS = {"recurring", "featured", "event", "events"}
MONTH_TOKEN = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)(?:[a-z]{0,6})\b"

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "")).strip()
    # Strip leading “Recurring”, “Featured”, etc.
    t = re.sub(rf"^({'|'.join(w.capitalize() for w in _BADGE_WORDS)})\b[:\-–]?\s*", "", t).strip()
    t = re.sub(rf"^({'|'.join(_BADGE_WORDS)})\b[:\-–]?\s*", "", t, flags=re.I).strip()
    return t

def _find_title_anchor(card) -> Optional[str]:
    # Prefer Modern Tribe title anchors
    for sel in [
        "a.tribe-events-calendar-list__event-title-link",
        '[data-js="tribe-events-event-title"] a',
        "h3 a", "h2 a",
        "a.tribe-event-url",
    ]:
        a = card.select_one(sel)
        if a and a.get("href"):
            title = _clean_title(_text(a))
            if title:
                return title
    # fallback
    a = card.find("a", href=True)
    return _clean_title(_text(a)) if a else None

def _find_url(card, base_url: str) -> str:
    for sel in [
        "a.tribe-events-calendar-list__event-title-link",
        '[data-js="tribe-events-event-title"] a',
        "h3 a", "h2 a",
        "a.tribe-event-url",
        "a",
    ]:
        a = card.select_one(sel)
        if a and a.get("href"):
            return urljoin(base_url, a["href"])
    return base_url

def _find_date_text(card) -> str:
    # Prefer explicit date/time nodes
    for sel in [".tribe-event-date-start", ".tribe-event-date", "time", ".tribe-events-c-small-cta__date"]:
        el = card.select_one(sel)
        if el:
            if el.name == "time" and el.has_attr("datetime"):
                return el["datetime"]
            return _text(el)
    # fallback: any line in card that looks date-like
    txt = _text(card)
    # keep only substrings that look like dates/months
    m = re.search(rf"{MONTH_TOKEN}[^|,\n]{{0,80}}", txt, re.I)
    return m.group(0).strip() if m else txt

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    cards = soup.select(
        "article.tribe-events-calendar-list__event, "
        ".tribe-events-calendar-list__event, "
        ".tribe-events-event-card, "
        "article, li.tribe-events-list-event"
    )
    if not cards:
        cards = soup.select(".tribe-common-g-row, li")

    for c in cards:
        title = _find_title_anchor(c)
        if not title or title.lower() in {"events", "calendar"}:
            continue
        url = _find_url(c, base_url)
        dt = _find_date_text(c)
        if not dt or title.lower() in _BADGE_WORDS:
            continue
        items.append({"title": title, "start": dt, "url": url, "location": ""})

    return items
