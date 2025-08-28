# src/parsers/modern_tribe.py
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
from utils.dates import parse_datetime_range, parse_iso_or_text
from utils.jsonld import extract_events_from_jsonld


def _prefer_times(container) -> tuple | None:
    # 1) <time datetime>
    times = container.select("time[datetime]")
    if times:
        try:
            start = parse_iso_or_text(times[0]["datetime"])
            end = parse_iso_or_text(times[1]["datetime"]) if len(times) > 1 else start
            return (start, end)
        except Exception:
            pass
    # 2) itemprop microdata
    start_meta = container.select_one('[itemprop="startDate"][content]')
    if start_meta:
        try:
            start = parse_iso_or_text(start_meta["content"])
            end_meta = container.select_one('[itemprop="endDate"][content]')
            end = parse_iso_or_text(end_meta["content"]) if end_meta else start
            return (start, end)
        except Exception:
            pass
    return None


def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    # 0) JSON-LD (very common on TEC)
    for ev in extract_events_from_jsonld(soup):
        title = (ev.get("name") or "Untitled").strip()
        url = ev.get("url") or base_url
        start_raw = ev.get("startDate") or ev.get("startTime") or ""
        end_raw = ev.get("endDate") or ev.get("endTime") or start_raw
        try:
            start = parse_iso_or_text(start_raw)
            end = parse_iso_or_text(end_raw, default=start)
            out.append(Event(title=title, start=start, end=end, url=url).__dict__)
        except Exception:
            pass

    # 1) TEC 6 selectors (newer sites, e.g., St. Germain)
    tec_cards = soup.select(".tec-events .tec-event, .tec-events .tec-events__event, [data-tec-event]")
    for card in tec_cards:
        title_a = card.select_one(".tec-event__title a, a.tec-event__title-link, h3 a")
        title = (_text(title_a) or _text(card.select_one(".tec-event__title")) or "Untitled").strip()
        url = title_a["href"] if title_a and title_a.has_attr("href") else base_url

        dt = _prefer_times(card)
        if not dt:
            # smaller date block
            dt_block = card.select_one(".tec-event__schedule, .tec-event__date, time")
            maybe = try_parse_datetime_range(_text(dt_block) if dt_block else "")
            if not maybe:
                continue
            start, end = maybe
        else:
            start, end = dt

        venue = card.select_one(".tec-event__venue, .tec-venue, .venue, .location")
        desc = card.select_one(".tec-event__description, .description, .summary")

        out.append(Event(
            title=title, start=start, end=end, url=url,
            location=_text(venue) or None,
            description=_text(desc) or None
        ).__dict__)

    # 2) Legacy TEC selectors (older “tribe-” classes)
    legacy_cards = soup.select(".tribe-events-calendar-list__event, .tribe-events-list-event, [data-event]")
    for card in legacy_cards:
        title_a = card.select_one(
            "a.tribe-events-calendar-list__event-title-link, "
            ".tribe-events-list-event-title a[rel=bookmark], "
            ".tribe-events-event-title a, "
            "h3 a"
        )
        title = (_text(title_a) or _text(card.select_one("h3")) or "Untitled").strip()
        url = title_a["href"] if title_a and title_a.has_attr("href") else base_url

        dt = _prefer_times(card)
        if not dt:
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
        else:
            start, end = dt

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

    # 3) Last-resort: look for event-ish links and a nearby time
    if not out:
        for block in soup.select("article, li, .event, .list, [role='listitem']"):
            a = block.select_one("a[href*='/event/'], a[href*='?eventDisplay='], a[href*='/events/']")
            if not a:
                continue
            dt = _prefer_times(block) or try_parse_datetime_range(_text(block))
            if not dt:
                continue
            start, end = dt
            title = (_text(a) or "Untitled").strip()
            url = a["href"] if a.has_attr("href") else base_url
            out.append(Event(title=title, start=start, end=end, url=url).__dict__)

    return out
