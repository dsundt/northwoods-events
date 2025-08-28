from __future__ import annotations
import os, sys
_PARSERS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_PARSERS_DIR)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from typing import List, Dict, Any
from bs4 import BeautifulSoup

from parsers._text import text as _text
from models import Event
from utils.dates import try_parse_datetime_range, parse_iso_or_text
from utils.jsonld import extract_events_from_jsonld

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    # 0) JSON-LD fallback catches a lot of sites
    for ev in extract_events_from_jsonld(soup):
        title = (ev.get("name") or "Untitled").strip()
        url = ev.get("url") or base_url
        start_raw = ev.get("startDate") or ev.get("startTime") or ""
        end_raw   = ev.get("endDate")   or ev.get("endTime")   or start_raw
        try:
            start = parse_iso_or_text(start_raw)
            end   = parse_iso_or_text(end_raw, default=start)
            out.append(Event(title=title, start=start, end=end, url=url).__dict__)
        except Exception:
            pass  # try DOM route too

    # 1) DOM route
    cards = soup.select(
        ".tribe-events-calendar-list__event, .tribe-events-list-event, [data-event]"
    )
    for card in cards:
        # Prefer the bookmark/permalink anchor inside each card
        title_a = card.select_one(
            "a.tribe-events-calendar-list__event-title-link, "
            ".tribe-events-list-event-title a[rel=bookmark], "
            ".tribe-events-event-title a, "
            "h3 a"
        )
        title = (_text(title_a) or _text(card.select_one("h3")) or "Untitled").strip()
        url = title_a["href"] if title_a and title_a.has_attr("href") else base_url

        # Prefer machine-readable <time datetime>
        times = card.select("time[datetime]")
        start = end = None
        if times:
            try:
                start = parse_iso_or_text(times[0]["datetime"])
                end   = parse_iso_or_text(times[1]["datetime"]) if len(times) > 1 else start
            except Exception:
                start = end = None

        # Fallback to a small date block only (avoid whole-card marketing copy)
        if start is None:
            dt_block = card.select_one(
                ".tribe-events-calendar-list__event-datetime, "
                ".tribe-event-date-start, "
                ".tribe-events-schedule, "
                "time"
            )
            maybe = try_parse_datetime_range(_text(dt_block) if dt_block else "")
            if not maybe:
                continue
            start, end = maybe

        venue = card.select_one(
            ".tribe-events-calendar-list__event-venue, .tribe-venue, .venue, .location"
        )
        desc = card.select_one(
            ".tribe-events-calendar-list__event-description, "
            ".tribe-events-list-event-description, .description, .summary"
        )

        out.append(Event(
            title=title, start=start, end=end, url=url,
            location=_text(venue) or None,
            description=_text(desc) or None
        ).__dict__)

    return out
