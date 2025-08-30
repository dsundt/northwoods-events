# src/parse_modern_tribe.py
from __future__ import annotations

from bs4 import BeautifulSoup
from .fetch import fetch_html
from .normalize import normalize_event, parse_dt, clean_text
from .utils.jsonld import extract_events_from_jsonld
from .utils.filters import is_date_like_title, is_recurring_text

def _location_from_jsonld(loc):
    if not loc:
        return ""
    if isinstance(loc, str):
        return loc
    if isinstance(loc, dict):
        name = loc.get("name") or ""
        addr = loc.get("address")
        if isinstance(addr, dict):
            parts = [addr.get("streetAddress"), addr.get("addressLocality"), addr.get("addressRegion")]
            address = ", ".join(p for p in parts if p)
        else:
            address = str(addr or "")
        return ", ".join(p for p in [name, address] if p)
    if isinstance(loc, list):
        return ", ".join(_location_from_jsonld(x) for x in loc if x)
    return ""

def parse_modern_tribe(source, add_event):
    url = source["url"]
    tzname = source.get("tzname")
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    # 1) Prefer schema.org Event JSON-LD (most reliable)
    had_any = False
    for ev in extract_events_from_jsonld(soup):
        title = clean_text(ev.get("name") or "")
        if not title or is_date_like_title(title):
            continue
        if is_recurring_text(ev.get("eventSchedule", "")):
            continue

        start_iso = ev.get("startDate") or ""
        end_iso   = ev.get("endDate") or ""
        loc       = _location_from_jsonld(ev.get("location"))
        link      = ev.get("url") or url

        evt = normalize_event(
            title=title,
            url=link,
            where=loc,
            start=parse_dt(start_iso, tzname),
            end=parse_dt(end_iso, tzname) if end_iso else None,
            tzname=tzname,
            description=clean_text(ev.get("description") or "")
        )
        if evt:
            add_event(evt)
            had_any = True

    if had_any:
        return

    # 2) Fallback: TEC list cards
    cards = soup.select(".tribe-events-calendar-list__event, .tribe-common .tribe-events-calendar-list__event-row, article.type-tribe_events")
    for card in cards:
        labels = " ".join(x.get_text(" ", strip=True) for x in card.select(".tribe-common-c-category, .tribe-event-tags, .tribe-events-event-labels"))
        if is_recurring_text(labels):
            continue

        a = card.select_one("a.tribe-events-calendar-list__event-title-link, a.tribe-event-url, h3 a, .tribe-events-event-meta a")
        title = clean_text(a.get_text(" ", strip=True) if a else card.get_text(" ", strip=True))
        if not title or is_date_like_title(title):
            continue
        link = a["href"] if a and a.has_attr("href") else url

        t_start = card.select_one("time[datetime]")
        start_iso = (t_start.get("datetime") or t_start.get_text(" ", strip=True)) if t_start else ""
        t_end_all = card.select("time[datetime]")
        end_iso = t_end_all[1].get("datetime") if len(t_end_all) > 1 else ""

        loc_el = card.select_one(".tribe-events-venue-details, .tribe-events-venue, .tribe-events-calendar-list__event-venue")
        where = clean_text(loc_el.get_text(" ", strip=True) if loc_el else "")

        evt = normalize_event(
            title=title,
            url=link,
            where=where,
            start=parse_dt(start_iso, tzname),
            end=parse_dt(end_iso, tzname) if end_iso else None,
            tzname=tzname,
        )
        if evt:
            add_event(evt)
