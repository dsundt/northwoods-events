from __future__ import annotations

from bs4 import BeautifulSoup
from typing import Iterable, Dict, Any, List
from .utils import clean, absolutize
from ..normalize import parse_datetime_range, clean_text

def parse(html: str, base_url: str) -> Iterable[Dict[str, Any]]:
    """
    Robust Modern Tribe (The Events Calendar) list parser.
    Works against list views that don’t expose the JSON API.
    """
    soup = BeautifulSoup(html, "lxml")

    # Most reliable: cards inside the list container
    cards: List = []
    cards.extend(soup.select(".tribe-events-calendar-list__event"))
    cards.extend(soup.select("article.type-tribe_events"))
    cards = list(dict.fromkeys(cards))  # de-dupe

    for card in cards:
        # Title
        title_el = (
            card.select_one(".tribe-events-calendar-list__event-title a")
            or card.select_one("h3 a")
            or card.select_one(".tribe-events-event-title a")
            or card.select_one("a.tribe-event-url")
        )
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""

        # URL
        url = absolutize(base_url, title_el.get("href")) if title_el and title_el.has_attr("href") else base_url

        # Date/time hints
        # Prefer machine times when present
        start_iso = None
        end_iso = None
        time_start = card.select_one("time.tribe-events-calendar-list__event-datetime-start")
        if time_start and time_start.has_attr("datetime"):
            start_iso = time_start["datetime"].strip()

        time_end = card.select_one("time.tribe-events-calendar-list__event-datetime-end")
        if time_end and time_end.has_attr("datetime"):
            end_iso = time_end["datetime"].strip()

        # Human fallback (e.g., “Aug 27 @ 6:30 pm – 8:00 pm”)
        date_text_el = (
            card.select_one(".tribe-events-calendar-list__event-datetime")
            or card.select_one(".tribe-event-schedule-details")
            or card
        )
        date_text = clean_text(date_text_el.get_text(" ", strip=True)) if date_text_el else ""

        start_dt, end_dt, all_day = parse_datetime_range(
            date_text=date_text,
            iso_hint=start_iso,
            iso_end_hint=end_iso,
            tzname="America/Chicago",
        )

        # Location (lightweight; many sites omit)
        loc_el = (
            card.select_one(".tribe-events-calendar-list__event-venue")
            or card.select_one(".tribe-venue")
            or card.select_one(".tribe-address")
        )
        location = clean_text(loc_el.get_text(" ", strip=True)) if loc_el else ""

        # Skip noise rows that had no real title and just point to list page
        if not title or url.rstrip("/").endswith("/?eventDisplay=list"):
            continue

        yield {
            "title": title,
            "url": url,
            "location": location,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "all_day": all_day,
        }
