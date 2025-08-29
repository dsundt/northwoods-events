# parse_simpleview.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import normalize_event, parse_dt


def parse_simpleview(source, add_event):
    url = source["url"]
    # pass source to honor wait_selector like ".event-listing"
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    cards = soup.select(".event-listing .event, .results .event, .lv-event, .sv-events .event")
    for el in cards:
        title_el = el.select_one("a, h3, .title")
        title = (title_el.get_text(" ", strip=True) if title_el else "").strip()
        if not title:
            continue
        link = title_el["href"].strip() if title_el and title_el.has_attr("href") else url

        start = None
        dt_el = el.select_one("time[datetime], .date, .event-date")
        if dt_el:
            iso = dt_el.get("datetime") or dt_el.get_text(" ", strip=True)
            start = parse_dt(iso, source.get("tzname"))

        evt = normalize_event(
            title=title,
            url=link,
            where=None,
            start=start,
            end=None,
            tzname=source.get("tzname"),
        )
        if evt:
            add_event(evt)
