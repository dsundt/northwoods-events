from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils.dates import parse_datetime_range, combine_date_and_time

__all__ = ["parse_modern_tribe"]

# Prefer the event-title anchor and the first <time datetime="..."> on the card.
TITLE_SEL = (
    ".tribe-events-calendar-list__event-title a, "
    ".tribe-events-event-title a, "
    "h3.tribe-events-calendar-list__event-title a, "
    "h2.tribe-events-calendar-list__event-title a, "
    "h3 a, h2 a"
)
CARD_SEL = (
    "article.tribe-events-calendar-list__event, "
    ".tribe-events-calendar-list__event, "
    ".tribe-events-event-card, "
    "article"
)
BAD_TITLE = {"recurring", "view all", "view calendar"}

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _pick_title_anchor(card) -> Optional[Dict[str, str]]:
    # Prefer anchors with /event/ (an occurrence) over /series/ or /all/
    anchors = card.select(TITLE_SEL) or card.select("h3 a, h2 a, a")
    chosen = None
    for a in anchors:
        href = a.get("href") or ""
        txt = a.get_text(strip=True)
        if not txt or txt.lower() in BAD_TITLE:
            continue
        if "/event/" in href and not href.endswith("/all/"):
            chosen = a
            break
        if chosen is None:
            chosen = a
    if not chosen:
        return None
    return {"title": chosen.get_text(strip=True), "href": chosen.get("href", "")}

def _pick_date_time(card) -> Optional[str]:
    # Try <time datetime="YYYY-MM-DD[...]"> on the card
    t = card.find("time", attrs={"datetime": True})
    if t:
        date_attr = t.get("datetime", "").split("T")[0]  # normalize to YYYY-MM-DD
        # Prefer any time strings inside the same time/line
        time_text = t.get_text(" ", strip=True)
        if not time_text:
            # occasionally time is elsewhere on the card, grab a likely fragment
            time_text = _text(card.find(class_=re.compile(r"time|hours", re.I))) or ""
        return combine_date_and_time(date_attr, time_text)

    # Fallback: parse freeform date/time from card text (handles 'October 4 - October 5', etc.)
    txt = _text(card)
    try:
        return parse_datetime_range(txt)
    except Exception:
        return None

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    cards = soup.select(CARD_SEL)
    if not cards:
        # Older markup: try row/list items
        cards = soup.select("li.tribe-events-list-event, .tribe-common-g-row")

    for c in cards:
        title_info = _pick_title_anchor(c)
        if not title_info:
            continue

        title = title_info["title"]
        href = urljoin(base_url, title_info["href"])
        # Avoid series/all links if a better /event/ link exists on the same card
        if "/series/" in href or href.endswith("/all/"):
            a2 = c.select_one('a[href*="/event/"]:not([href$="/all/"])')
            if a2:
                href = urljoin(base_url, a2.get("href", ""))

        start_iso = _pick_date_time(c)
        if not start_iso:
            # Last-ditch: try title text for a date fragment (e.g., 'October 4')
            try:
                start_iso = parse_datetime_range(title)
            except Exception:
                continue  # skip container rows that aren’t real events

        # Location (best-effort)
        loc_el = c.find(class_=re.compile(r"(venue|location|address)", re.I))
        location = _text(loc_el) if loc_el else ""

        items.append({
            "title": title,
            "start": start_iso,
            "url": href,
            "location": location,
        })

    return items
