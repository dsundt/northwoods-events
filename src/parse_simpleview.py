# src/parse_simpleview.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import normalize_event, parse_dt

def parse_simpleview(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    cards = soup.select(".event-listing .event, .results .event, .lv-event, .sv-events .event")
    if not cards:
        cards = soup.select("article, li, div")

    for el in cards:
        title = None
        link = None
        start = None

        h = el.select_one(".event-title, h3, h2, a")
        if h:
            title = h.get_text(" ", strip=True)
            a = h.find("a") or (h if h.name == "a" else None)
            if a and a.has_attr("href"):
                link = a["href"]

        dt_el = el.select_one("time[datetime]")
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
