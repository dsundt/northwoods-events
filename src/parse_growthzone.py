# src/parse_growthzone.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import normalize_event, parse_dt

def parse_growthzone(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    wrappers = soup.select(
        ".mn-content .listing, .cm-body .listing, .mn-list .listing, .listing, "
        ".mn-event, .mn-event-card, li.event, div.event, .mn-calendar .mn-CalendarItem"
    )
    if not wrappers:
        wrappers = soup.select("article, li, div")

    for el in wrappers:
        title = None
        link = None
        start = None

        t_el = el.select_one("h3 a, .title a, a.mn-EventTitle, a.event-title, a")
        if t_el:
            title = t_el.get_text(" ", strip=True)
            link = t_el.get("href")

        dt_el = el.select_one("time[datetime], .mn-CalendarDate, .mn-date, .date, .event-date")
        if dt_el:
            iso = dt_el.get("datetime") or dt_el.get_text(" ", strip=True)
            start = parse_dt(iso, source.get("tzname"))

        evt = normalize_event(
            title=title or "",
            url=link,
            where=None,
            start=start,
            end=None,
            tzname=source.get("tzname"),
            source_name=source.get("name"),
        )
        if evt:
            add_event(evt)
