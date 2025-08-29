# src/parse_growthzone.py
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
        if name and start:
            evt = normalize_event(
                title=name,
                url=url,
                where=where,
                start=start,
                end=end,
                tzname=source.get("tzname"),
                description=clean_text(j.get("description")),
                all_day=False,
                source_name=source.get("name"),
            )
            if evt:
                add_event(evt)
                found = True
    return found

def parse_growthzone(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    if _try_jsonld(source, soup, add_event):
        return

    wrappers = soup.select(
        ".mn-content .listing, .cm-body .listing, .mn-list .listing, .listing, "
        ".mn-event, .mn-event-card, li.event, div.event, .mn-calendar .mn-CalendarItem"
    )
    if not wrappers:
        wrappers = soup.select("article, li, div")

    for w in wrappers:
        a = w.select_one("a[href]")
        title = clean_text(a.get_text(" ", strip=True) if a else w.get_text(" ", strip=True))
        link = a.get("href") if a and a.has_attr("href") else url

        # time can be in <time datetime="..."> or text
        start = end = None
        all_day = False

        t = w.select_one("time[datetime]")
        if t and (t.get("datetime") or t.get_text(strip=True)):
            iso = t.get("datetime") or t.get_text(" ", strip=True)
            s, e, ad = parse_datetime_range(iso, source.get("tzname"))
            start, end, all_day = s, e, ad

        if not start:
            ttxt = w.get_text(" ", strip=True)
            s, e, ad = parse_datetime_range(ttxt, source.get("tzname"))
            start, end = s, e
            all_day = all_day or ad

        evt = normalize_event(
            title=title or "",
            url=link,
            where=None,
            start=start,
            end=end,
            tzname=source.get("tzname"),
            description=None,
            all_day=all_day,
            source_name=source.get("name"),
        )
        if evt:
            add_event(evt)
