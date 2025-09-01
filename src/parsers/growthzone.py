from __future__ import annotations
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from .utils import soupify, clean_text, abs_url
import json

def _parse_jsonld(soup: BeautifulSoup, base_url: str, source_name: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = []
        if isinstance(data, dict):
            if data.get("@type") in ("Event",):
                items = [data]
            elif "@graph" in data and isinstance(data["@graph"], list):
                items = [x for x in data["@graph"] if isinstance(x, dict) and x.get("@type") == "Event"]
        elif isinstance(data, list):
            items = [x for x in data if isinstance(x, dict) and x.get("@type") == "Event"]
        for e in items:
            title = clean_text(e.get("name"))
            start = e.get("startDate") or e.get("startTime")
            end   = e.get("endDate") or e.get("endTime")
            url   = abs_url(base_url, e.get("url"))
            loc = e.get("location") or {}
            loc_name = ""
            if isinstance(loc, dict):
                loc_name = clean_text(loc.get("name"))
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

def _parse_cards(soup: BeautifulSoup, base_url: str, source_name: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cards = soup.select("div.card, div.event, div.listing, li.event, div.calendar-event")
    for c in cards:
        a = c.select_one("a[href]")
        t = c.select_one("h3, h2, .title, .event-title")
        time_el = c.select_one("time[datetime]")
        title = clean_text((t or a).get_text() if (t or a) else "")
        url = abs_url(base_url, a["href"]) if a and a.has_attr("href") else None
        start = time_el["datetime"] if time_el and time_el.has_attr("datetime") else ""
        loc_el = c.select_one(".location, .venue, .event-location")
        loc = clean_text(loc_el.get_text()) if loc_el else ""
        if title and start:
            out.append({
                "title": title,
                "start": start,
                "end": None,
                "location": loc,
                "url": url,
                "source": source_name,
            })
    return out

def parse_growthzone(html: str, base_url: str, tzname: Optional[str], source_name: str) -> List[Dict[str, Any]]:
    soup = soupify(html)
    events = _parse_jsonld(soup, base_url, source_name)
    if not events:
        events = _parse_cards(soup, base_url, source_name)
    return events
