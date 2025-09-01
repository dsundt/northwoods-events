from __future__ import annotations
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from .utils import soupify, clean_text, abs_url
from urllib.parse import urljoin
import json, datetime as dt

def _parse_jsonld_events(soup: BeautifulSoup, base_url: str, tzname: Optional[str], source_name: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = []
        if isinstance(data, dict):
            if data.get("@type") in ("Event","Festival","EducationEvent","ExhibitionEvent","MusicEvent","TheaterEvent","ComedyEvent"):
                items = [data]
            elif "@graph" in data and isinstance(data["@graph"], list):
                items = [x for x in data["@graph"] if isinstance(x, dict) and x.get("@type") in ("Event","Festival","EducationEvent","ExhibitionEvent","MusicEvent","TheaterEvent","ComedyEvent")]
        elif isinstance(data, list):
            items = [x for x in data if isinstance(x, dict) and x.get("@type") in ("Event","Festival","EducationEvent","ExhibitionEvent","MusicEvent","TheaterEvent","ComedyEvent")]

        for e in items:
            title = clean_text(e.get("name"))
            start = e.get("startDate") or e.get("startTime")
            end   = e.get("endDate") or e.get("endTime")
            url   = e.get("url")
            loc_name = ""
            loc = e.get("location")
            if isinstance(loc, dict):
                loc_name = clean_text(loc.get("name") or "")
            elif isinstance(loc, str):
                loc_name = clean_text(loc)
            if not url:
                # sometimes URL is nested
                url = e.get("mainEntityOfPage") or None
            url = abs_url(base_url, url)
            if not start and e.get("eventSchedule"):
                # Some JSON-LD uses eventSchedule with repeat; skip for now
                continue
            if title and start:
                out.append({
                    "title": title,
                    "start": start,
                    "end": end,
                    "location": loc_name,
                    "url": url,
                    "source": source_name,
                })
    return out

def _parse_card_list(soup: BeautifulSoup, base_url: str, tzname: Optional[str], source_name: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # The Events Calendar common list item selectors
    candidates = soup.select(
        "article.tribe-events-calendar-list__event, "
        "div.tribe-events-calendar-list__event, "
        "div.tec-list__item, "
        "div.tec-event-card, "
        "div.tribe-common-event"
    )
    for el in candidates:
        title_el = el.select_one("h3 a, h2 a, a.tribe-event-url, a.tec-event__title-link")
        dt_el = el.select_one("time[datetime], .tribe-event-date-start, .tec-event-datetime__start")
        url = abs_url(base_url, title_el["href"]) if title_el and title_el.has_attr("href") else None
        title = clean_text(title_el.get_text()) if title_el else ""
        start = dt_el["datetime"] if dt_el and dt_el.has_attr("datetime") else ""
        loc_el = el.select_one(".tribe-events-venue__name, .tec-venue__name, .tribe-event-venue")
        location = clean_text(loc_el.get_text()) if loc_el else ""
        if title and start:
            out.append({
                "title": title,
                "start": start,
                "end": None,
                "location": location,
                "url": url,
                "source": source_name,
            })
    return out

def parse_modern_tribe(html: str, base_url: str, tzname: Optional[str], source_name: str) -> List[Dict[str, Any]]:
    soup = soupify(html)
    events = _parse_jsonld_events(soup, base_url, tzname, source_name)
    if not events:
        events = _parse_card_list(soup, base_url, tzname, source_name)
    return events
