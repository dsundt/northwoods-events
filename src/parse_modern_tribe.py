# parse_modern_tribe.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import parse_dt, normalize_event


def parse_modern_tribe(source, add_event):
    url = source["url"]
    # pass source for wait hints like ".tec-events"
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    # Your existing Modern Tribe parsing logic (kept minimal here)
    # Common item: article or li with event classes
    cards = soup.select(".tec-events .tec-event, .tribe-events .type-tribe_events, article.tribe-events-calendar-list__event")
    for card in cards:
        title_el = card.select_one("a, h3, .tribe-events-calendar-list__event-title")
        title = (title_el.get_text(" ", strip=True) if title_el else "").strip()
        if not title:
            continue

        link_el = card.select_one("a[href]")
        link = link_el["href"].strip() if link_el and link_el.has_attr("href") else url

        # Dates vary wildly; keep defensive
        start = None
        end = None
        dt_el = card.select_one("time[datetime]")
        if dt_el and dt_el.has_attr("datetime"):
            start = parse_dt(dt_el["datetime"], source.get("tzname"))

        evt = normalize_event(
            title=title,
            url=link,
            where=None,
            start=start,
            end=end,
            tzname=source.get("tzname"),
        )
        if evt:
            add_event(evt)
