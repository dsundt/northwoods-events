# src/parse_simpleview.py
from __future__ import annotations
import requests
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from .utils.jsonld import extract_events_from_jsonld
from .utils import norm_event, clean_text, save_debug_html

UA = "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0; +https://example.invalid)"

def _fetch_html(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text

def parse_simpleview(name: str, url: str, tzname: Optional[str] = None) -> List[Dict[str, Any]]:
    html = _fetch_html(url)
    save_debug_html(html, filename=f"simpleview_{name.replace(' ','_')}")
    # 1) Prefer JSON-LD
    events = extract_events_from_jsonld(html, source_name=name, default_tz=tzname)
    if events:
        return [norm_event(e) for e in events]

    # 2) Gentle HTML fallback for Simpleview "list" view
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("li.grid__item, .card, .event")
    out: List[Dict[str, Any]] = []
    for c in cards:
        a = c.select_one("a[href]")
        title = clean_text(a.get_text(" ", strip=True)) if a else ""
        href = a["href"] if a and a.has_attr("href") else url
        date = c.get("data-date") or ""
        place = c.select_one(".location, .event__location, .card__location")
        loc = clean_text(place.get_text(" ", strip=True)) if place else ""
        if title:
            out.append(norm_event({
                "title": title,
                "start": date or None,
                "end": None,
                "url": href,
                "location": loc,
                "source": name,
            }))
    return out
