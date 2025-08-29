# src/parse_ai1ec.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import parse_datetime_range, normalize_event, clean_text

def parse_ai1ec(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    items = soup.select(".ai1ec-event, .ai1ec-event-container, article, li")
    if not items:
        items = soup.select("div")

    for it in items:
        a = it.select_one("a[href]")
        title = clean_text(a.get_text(" ", strip=True) if a else it.get_text(" ", strip=True))
        link = a.get("href") if a and a.has_attr("href") else url

        date_el = it.select_one("time[datetime], .ai1ec-event-time, .ai1ec-event-time-range, .ai1ec-time")
        date_text = date_el.get("datetime") if date_el and date_el.has_attr("datetime") else (
            date_el.get_text(" ", strip=True) if date_el else it.get_text(" ", strip=True)
        )
        start, end, all_day = parse_datetime_range(date_text or "", source.get("tzname"))

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
