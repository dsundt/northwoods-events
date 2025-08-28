from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.dates import parse_datetime_range

__all__ = ["parse_modern_tribe"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

HEADER_WORDS = {"events", "featured events", "upcoming events"}
TIME_CLASSES = (
    "tribe-event-date-start",
    "tribe-event-date",
    "tribe-events-calendar-list__event-date-tag",
)

def _pick_datetime(card) -> Optional[str]:
    # 1) semantic <time> tag with datetime attr
    time_el = card.find("time", attrs={"datetime": True})
    if time_el and time_el.get("datetime"):
        dt = time_el["datetime"].strip()
        # Some sites put ISO here already; accept
        if re.match(r"^\d{4}-\d{2}-\d{2}", dt):
            return dt
        # Otherwise try to parse whatever is inside
        try:
            return parse_datetime_range(_text(time_el))
        except Exception:
            pass

    # 2) text blocks likely holding the date/time
    for cls in TIME_CLASSES:
        el = card.select_one(f".{cls}")
        if el:
            t = _text(el)
            if t and t.lower() not in HEADER_WORDS:
                try:
                    return parse_datetime_range(t)
                except Exception:
                    pass

    # 3) last-ditch: parse from whole card text (but never from bare "Events")
    body = _text(card)
    if body and body.lower() not in HEADER_WORDS:
        try:
            return parse_datetime_range(body)
        except Exception:
            return None
    return None

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Typical containers
    cards = soup.select("article, .tribe-events-calendar-list__event, .tribe-events-event-card")
    if not cards:
        cards = soup.select(".tribe-common-g-row, li.tribe-events-list-event")

    for c in cards:
        # anchor & URL
        a = c.find("a", href=True)
        url = urljoin(base_url, a["href"]) if a else base_url

        # clean title: prefer heading text, else anchor text; drop “Recurring”
        title = _text(c.find(["h3", "h2"])) or _text(a)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or title.lower() in {"recurring"}:
            # Some list rows labelled "Recurring" (Boulder Junction) – use series title if present
            series = c.find(class_=re.compile(r"(?:series|title)", re.I))
            title = _text(series) or title
        if not title or title.lower() in {"events", "recurring"}:
            continue

        start = _pick_datetime(c)
        if not start:
            # Skip container rows that aren’t real events (prevents “10:00 am” only etc.)
            continue

        # optional location
        loc_el = c.find(class_=re.compile(r"(venue|location)", re.I))
        location = _text(loc_el)

        items.append({"title": title, "start": start, "url": url, "location": location})

    return items
