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

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    # JSON-LD first
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

    # DOM route with itemprop hints
    for c in soup.select("article, li, .event, [data-result], .cards .card"):
        title_a = c.select_one("a[href]")
        title = (_text(title_a) or _text(c.select_one('meta[itemprop="name"]')) or "Untitled").strip()
        url = title_a["href"] if title_a and title_a.has_attr("href") else base_url

        # Prefer schema.org microdata
        start_meta = c.select_one('[itemprop="startDate"][content]')
        end_meta   = c.select_one('[itemprop="endDate"][content]')
        start = end = None
        if start_meta:
            try:
                start = parse_iso_or_text(start_meta["content"])
                end   = parse_iso_or_text(end_meta["content"]) if end_meta else start
            except Exception:
                start = end = None

        if start is None:
            dt_block = c.select_one(".date, .event-date, time")
            maybe = try_parse_datetime_range(_text(dt_block) if dt_block else "")
            if not maybe:
                continue
            start, end = maybe

        venue = c.select_one(".venue, .location, [itemprop='location']")
        desc  = c.select_one(".summary, .description, [itemprop='description']")

        out.append(Event(
            title=title, start=start, end=end, url=url,
            location=_text(venue) or None,
            description=_text(desc) or None
        ).__dict__)

    return out
