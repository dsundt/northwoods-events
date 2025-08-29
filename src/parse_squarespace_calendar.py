# parse_squarespace_calendar.py
from __future__ import annotations

from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import normalize_event, parse_dt


def _first_text(el, selectors):
    for sel in selectors:
        node = el.select_one(sel)
        if node:
            t = node.get_text(" ", strip=True)
            if t:
                return t
    return ""


def _first_href(el, selectors):
    for sel in selectors:
        a = el.select_one(sel)
        if a and a.has_attr("href"):
            return a["href"].strip()
    return None


def _first_datetime(el, selectors):
    t = el.select_one("time[datetime]")
    if t and t.has_attr("datetime"):
        return t["datetime"].strip()

    for sel in selectors:
        node = el.select_one(sel)
        if not node:
            continue
        t2 = node.get_text(" ", strip=True)
        if t2:
            return t2
    return None


def parse_squarespace_calendar(source, add_event):
    url = source["url"]
    html = fetch_html(url, source=source)
    soup = BeautifulSoup(html, "lxml")

    items = soup.select(
        "li.eventlist-item, article.eventlist-event, "
        ".eventlist .eventlist-item, .events .event-item, "
        ".events-list .event-item, .sqs-block-calendar .eventlist-item"
    )

    for el in items:
        title = _first_text(
            el,
            [".eventlist-title", ".event-title", "h3 a", "h3", "h2 a", "h2", "a"],
        )
        if not title:
            continue

        href = _first_href(el, ["a.eventlist-title-link", ".eventlist-title a", "h3 a", "h2 a", "a"])
        link = urljoin(url, href) if href else url

        dt_raw = _first_datetime(
            el,
            [".eventlist-datetime", ".event-date", ".event-time", ".event-meta", ".eventlist-meta"],
        )
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
