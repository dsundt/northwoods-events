# src/parse_modern_tribe.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import parse_dt, normalize_event

def parse_modern_tribe(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    cards = soup.select(
        "article.tribe-events-calendar-list__event, article.tec-events-calendar-list__event, "
        "div.tribe-events-calendar-list__event, li.tribe-events-calendar-list__event"
    )
    if not cards:
        # generic fallback
        cards = soup.select("article, li, div")

    for el in cards:
        title = None
        link = None
        start = None
        end = None

        # title + link
        h = el.select_one(".tribe-events-calendar-list__event-title, .tec-event__title, h3, h2, .event-title")
        if h:
            title = h.get_text(" ", strip=True)
            a = h.find("a")
            if a and a.has_attr("href"):
                link = a["href"]
        if not title:
            a = el.find("a")
            if a:
                title = a.get_text(" ", strip=True) or title
                if a.has_attr("href"):
                    link = a["href"]

        # time
        t = el.select_one("time[datetime]")
        if t and t.has_attr("datetime"):
            start = parse_dt(t["datetime"], source.get("tzname"))

        evt = normalize_event(
            title=title or "",
            url=link,
            where=None,
            start=start,
            end=end,
            tzname=source.get("tzname"),
            source_name=source.get("name"),
        )
        if evt:
            add_event(evt)
