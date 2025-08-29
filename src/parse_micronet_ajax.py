# parse_micronet_ajax.py
from __future__ import annotations

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .fetch import fetch_html
from .normalize import normalize_event, parse_dt

ITEM_SELECTORS = (
    ".cm-event, .event-item, li.event, .calendar-event, .EventList .Event, .eventItem"
)

def _text(el, selectors):
    for sel in selectors:
        n = el.select_one(sel)
        if n:
            t = n.get_text(" ", strip=True)
            if t:
                return t
    return ""

def _href(el, selectors):
    for sel in selectors:
        a = el.select_one(sel)
        if a and a.has_attr("href"):
            return a["href"].strip()
    return None

def parse_micronet_ajax(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    items = soup.select(ITEM_SELECTORS)
    for el in items:
        title = _text(el, [".cm-event-title a", ".cm-event-title", ".event-title a", ".event-title", "a", "h3 a", "h3"])
        if not title:
            continue

        href = _href(el, [".cm-event-title a", ".event-title a", "a"])
        link = urljoin(url, href) if href else url

        # Date: prefer <time datetime>, else text in known containers
        dt_raw = None
        t = el.select_one("time[datetime]")
        if t and t.has_attr("datetime"):
            dt_raw = t["datetime"].strip()
        if not dt_raw:
            dt_raw = _text(el, [".cm-event-date", ".event-date", ".date", ".meta", ".event-meta"])

        start = parse_dt(dt_raw, source.get("tzname")) if dt_raw else None

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
