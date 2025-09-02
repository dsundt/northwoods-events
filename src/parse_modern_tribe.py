# src/parse_modern_tribe.py
from __future__ import annotations
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from .utils.jsonld import extract_events_from_jsonld
from .utils import norm_event, clean_text, save_debug_html

UA = "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0; +https://example.invalid)"

def _fetch_html(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text

def parse_modern_tribe(name: str, url: str, tzname: Optional[str] = None) -> List[Dict[str, Any]]:
    html = _fetch_html(url)
    save_debug_html(html, filename=f"modern_tribe_{name.replace(' ','_')}")
    events = extract_events_from_jsonld(html, source_name=name, default_tz=tzname)
    if events:
        return [norm_event(e) for e in events]

    # Fallback: light HTML scrape for The Events Calendar v6 list view
    soup = BeautifulSoup(html, "lxml")
    items = soup.select("li.tribe-events-calendar-list__event, article.tribe-common-g-row")
    out: List[Dict[str, Any]] = []
    for it in items:
        title_el = it.select_one("h3 a, h2 a, a.tribe-events-calendar-list__event-title-link")
        title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""
        href = title_el["href"].strip() if title_el and title_el.has_attr("href") else url

        # Dates in list view are often present as data attributes; if not, let main normalize later
        dt_el = it.select_one("[data-tribe-common-event-start], time.tribe-event-date-start")
        start = (dt_el.get("data-tribe-common-event-start") or dt_el.get("datetime")) if dt_el else None
        end_el = it.select_one("[data-tribe-common-event-end], time.tribe-event-date-end")
        end = (end_el.get("data-tribe-common-event-end") or end_el.get("datetime")) if end_el else None

        loc_el = it.select_one(".tribe-events-calendar-list__event-venue, .tribe-venue, .tribe-events-venue-details")
        location = clean_text(loc_el.get_text(" ", strip=True)) if loc_el else ""

        if not title:
            continue

        out.append(norm_event({
            "title": title,
            "start": start,
            "end": end,
            "url": href,
            "location": location,
            "source": name,
        }))
    return out
