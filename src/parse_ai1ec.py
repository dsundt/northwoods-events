# parse_ai1ec.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import normalize_event, parse_dt


def parse_ai1ec(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)  # pass source for wait hints
    soup = BeautifulSoup(html, "lxml")

    items = soup.select(".ai1ec-event, .ai1ec-event-instance, article.ai1ec_event")
    for el in items:
        title_el = el.select_one(".ai1ec-event-title, h3 a, a")
        title = (title_el.get_text(" ", strip=True) if title_el else "").strip()
        if not title:
            continue
        link = title_el["href"].strip() if title_el and title_el.has_attr("href") else url

        start = None
        dt_el = el.select_one("time[datetime], .ai1ec-time")
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
