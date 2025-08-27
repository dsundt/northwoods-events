from __future__ import annotations

from bs4 import BeautifulSoup
from typing import Iterable, Dict, Any, List

# NOTE: import normalize absolutely (works when running python src/main.py)
from normalize import parse_datetime_range, clean_text
from .utils import clean, absolutize


def parse(html: str, base_url: str) -> Iterable[Dict[str, Any]]:
    """
    Robust Modern Tribe (The Events Calendar) list parser.
    Works against list views that don’t expose the JSON API.
    """
    soup = BeautifulSoup(html, "lxml")

    cards: List = []
    cards.extend(soup.select(".tribe-events-calendar-list__event"))
    cards.extend(soup.select("article.type-tribe_events"))
    cards = list(dict.fromkeys(cards))  # de-dupe

    for card in cards:
        title_el = (
            card.select_one(".tribe-events-calendar-list__event-title a")
            or card.select_one("h3 a")
            or card.select_one(".tribe-events-event-title a")
            or card.select_one("a.tribe-event-url")
        )
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""
        url = absolutize(base_url, title_el.get("href")) if title_el and title_el.has_attr("href") else base_url

        start_iso = None
        end_iso = None
        tstart = card.select_one("time.tribe-events-calendar-list__event-datetime-start")
        if tstart and tstart.has_attr("datetime"):
            start_iso = tstart["datetime"].strip()
        tend = card.select_one("time.tribe-events-calendar-list__event-datetime-end")
        if tend and tend.has_attr("datetime"):
            end_iso = tend["datetime"].strip()

        date_text_el = (
            card.select_one(".tribe-events-calendar-list__event-datetime")
            or card.select_one(".tribe-event-schedule-details")
            or card
        )
        date_text = clean_text(date_text_el.get_text(" ", strip=True)) if date_text_el else ""

        start_dt, end_dt, all_day = parse_datetime_range(
            date_text=date_text, iso_hint=start_iso, iso_end_hint=end_iso, tzname="America/Chicago"
        )

        loc_el = (
            card.select_one(".tribe-events-calendar-list__event-venue")
            or card.select_one(".tribe-venue")
            or card.select_one(".tribe-address")
        )
        location = clean_text(loc_el.get_text(" ", strip=True)) if loc_el else ""

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
