# src/parse_ai1ec.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import normalize_event, parse_dt

def parse_ai1ec(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    items = soup.select(".ai1ec-event, .ai1ec-event-instance, article.ai1ec_event, .event")
    if not items:
        items = soup.select("article, li, div")

    for el in items:
        title = None
        link = None
        start = None

        h = el.select_one(".ai1ec-event-title, h3, h2, a")
        if h:
            title = h.get_text(" ", strip=True)
            a = h.find("a") or (h if h.name == "a" else None)
            if a and a.has_attr("href"):
                link = a["href"]

        dt_el = el.select_one("time[datetime], .ai1ec-time, .ai1ec-date")
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
