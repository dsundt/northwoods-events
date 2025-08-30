# src/parse_simpleview.py
from __future__ import annotations

from bs4 import BeautifulSoup
from .fetch import fetch_html
from .normalize import normalize_event, parse_dt, clean_text
from .utils.jsonld import extract_events_from_jsonld
from .utils.filters import is_date_like_title

def _loc_from_jsonld(loc):
    if not loc:
        return ""
    if isinstance(loc, str):
        return loc
    if isinstance(loc, dict):
        name = loc.get("name") or ""
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            parts = [addr.get("streetAddress"), addr.get("addressLocality"), addr.get("addressRegion")]
            addr_s = ", ".join(p for p in parts if p)
        else:
            addr_s = str(addr or "")
        return ", ".join(p for p in [name, addr_s] if p)
    if isinstance(loc, list):
        return ", ".join(_loc_from_jsonld(x) for x in loc if x)
    return ""

def parse_simpleview(source, add_event):
    url = source["url"]
    tzname = source.get("tzname")
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    # 1) JSON-LD (most Simpleview sites include this)
    had = False
    for ev in extract_events_from_jsonld(soup):
        title = clean_text(ev.get("name") or "")
        if not title or is_date_like_title(title):
            continue
        start_iso = ev.get("startDate") or ""
        end_iso   = ev.get("endDate") or ""
        where     = _loc_from_jsonld(ev.get("location"))
        link      = ev.get("url") or url

        evt = normalize_event(
            title=title,
            url=link,
            where=where,
            start=parse_dt(start_iso, tzname),
            end=parse_dt(end_iso, tzname) if end_iso else None,
            tzname=tzname,
            description=clean_text(ev.get("description") or "")
        )
        if evt:
            add_event(evt)
            had = True

    if had:
        return

    # 2) Defensive card fallback for Simpleview themes
    cards = soup.select(".event-listing .event, .results .event, .lv-event, .sv-events .event")
    for card in cards:
        a = card.select_one("a[href]")
        title = clean_text(a.get_text(" ", strip=True) if a else card.get_text(" ", strip=True))
        if not title or is_date_like_title(title):
            continue
        link = a["href"] if a and a.has_attr("href") else url

        time_el = card.select_one("time[datetime], .date, .event-date, .sv-event-date")
        start_iso = (time_el.get("datetime") or time_el.get_text(" ", strip=True)) if time_el else ""
        where_el = card.select_one(".location, .venue, .event-location")
        where = clean_text(where_el.get_text(" ", strip=True) if where_el else "")

        evt = normalize_event(
            title=title,
            url=link,
            where=where,
            start=parse_dt(start_iso, tzname),
            end=None,
            tzname=tzname,
        )
        if evt:
            add_event(evt)
