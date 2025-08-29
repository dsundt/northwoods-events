# src/parse_simpleview.py
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

def parse_simpleview(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    if _try_jsonld(source, soup, add_event):
        return

    cards = soup.select(".event-listing .event, .results .event, .lv-event, .sv-events .event")
    if not cards:
        cards = soup.select("article, li, div")

    for c in cards:
        a = c.select_one("a[href]")
        title = clean_text(a.get_text(" ", strip=True) if a else c.get_text(" ", strip=True))
        link = a.get("href") if a and a.has_attr("href") else url

        # location
        loc = c.select_one(".venue, .event-venue, .event__venue, .sv-event-venue")
        where = clean_text(loc.get_text(" ", strip=True)) if loc else ""

        # time
        start = end = None
        all_day = False

        t = c.select_one("time[datetime], meta[itemprop='startDate'][content]")
        if t:
            iso = t.get("datetime") or t.get("content") or t.get_text(" ", strip=True)
            s, e, ad = parse_datetime_range(iso, source.get("tzname"))
            start, end, all_day = s, e, ad

        if not start:
            ttxt = c.get_text(" ", strip=True)
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
