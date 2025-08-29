# src/parse_modern_tribe.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import parse_dt, parse_datetime_range, normalize_event, clean_text
from .utils.jsonld import extract_events_from_jsonld

def _try_jsonld(source, soup, add_event):
    found = False
    for j in extract_events_from_jsonld(soup):
        name = clean_text(j.get("name") or j.get("headline"))
        url = j.get("url")
        where = None
        loc = j.get("location")
        if isinstance(loc, dict):
            where = clean_text(loc.get("name") or loc.get("address") or "")
        start = parse_dt(j.get("startDate", "") or "", source.get("tzname"))
        end = parse_dt(j.get("endDate", "") or "", source.get("tzname"))
        all_day = False
        if name and start:
            evt = normalize_event(
                title=name,
                url=url,
                where=where,
                start=start,
                end=end,
                tzname=source.get("tzname"),
                description=clean_text(j.get("description")),
                all_day=all_day,
                source_name=source.get("name"),
            )
            if evt:
                add_event(evt)
                found = True
    return found

def parse_modern_tribe(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    # JSON-LD first (Modern Tribe often includes it)
    if _try_jsonld(source, soup, add_event):
        return

    # Card selectors for Modern Tribe / TEC
    cards = soup.select(
        "article.tribe-events-calendar-list__event, "
        "article.tec-events-calendar-list__event, "
        "div.tribe-events-calendar-list__event, "
        "div.tec-events-calendar-list__event"
    )
    if not cards:
        # Very old themes sometimes use generic article or li
        cards = soup.select("article, li.tribe-events-calendar-list__event")

    for card in cards:
        # Title + link
        a = card.select_one("a.tribe-events-calendar-list__event-title-link, a.tec-event__title-link, h3 a, .tribe-event-url")
        title = clean_text(a.get_text(" ", strip=True) if a else card.get_text(" ", strip=True))
        link = a.get("href") if a and a.has_attr("href") else url

        # Location (best effort)
        loc_el = card.select_one(".tribe-events-venue-details, .tribe-venue, .tec-event__venue, .tribe-events-venue")
        where = clean_text(loc_el.get_text(" ", strip=True)) if loc_el else ""

        # Date/Time
        all_day = bool(card.select_one(".tribe-events-calendar-list__event-datetime--all-day, .tec-event-datetime--all-day"))
        start = end = None

        # Common MT/TEC time patterns
        time_el = card.select_one("time.tribe-events-calendar-list__event-date, time.tec-event-datetime__date, time")
        if time_el:
            # datetime attribute preferred
            iso = time_el.get("datetime") or time_el.get_text(" ", strip=True)
            if iso:
                s, e, ad = parse_datetime_range(iso, source.get("tzname"))
                start, end = s, e
                all_day = all_day or ad

        # Fallback: data-startdate attributes or text blocks
        if not start:
            ttxt = card.get_text(" ", strip=True)
            s, e, ad = parse_datetime_range(ttxt, source.get("tzname"))
            start, end = s, e
            all_day = all_day or ad

        evt = normalize_event(
            title=title or "",
            url=link,
            where=where,
            start=start,
            end=end,
            tzname=source.get("tzname"),
            description=None,
            all_day=all_day,
            source_name=source.get("name"),
        )
        if evt:
            add_event(evt)
