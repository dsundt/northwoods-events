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

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    # JSON-LD (many GrowthZone sites include it)
    for ev in extract_events_from_jsonld(soup):
        title = (ev.get("name") or "Untitled").strip()
        url = ev.get("url") or base_url
        start_raw = ev.get("startDate") or ""
        end_raw   = ev.get("endDate") or start_raw
        try:
            start = parse_iso_or_text(start_raw)
            end   = parse_iso_or_text(end_raw, default=start)
            out.append(Event(title=title, start=start, end=end, url=url).__dict__)
        except Exception:
            pass

    # DOM-based fallback
    for row in soup.select("li, article, .event-row, .event, .list-item"):
        a = row.select_one("a[href*='events/details']")
        if not a:
            continue
        title = (_text(a) or "Untitled").strip()
        url = a["href"] if a.has_attr("href") else base_url

        # Use the smallest date-ish region near the link
        dt_block = row.select_one("time, .date, .event-date, .when, .eventTime, .eventDate")
        maybe = try_parse_datetime_range(_text(dt_block) if dt_block else _text(row))
        if not maybe:
            continue
        start, end = maybe

        out.append(Event(title=title, start=start, end=end, url=url).__dict__)

    return out
