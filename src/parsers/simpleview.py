import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime

try:
    from ..normalize import parse_datetime_range, clean_text
    from ..types import Event
except Exception:
    from normalize import parse_datetime_range, clean_text  # type: ignore
    from types import Event  # type: ignore


def _text(el):
    return clean_text(el.get_text(" ", strip=True)) if el else ""


def parse_simpleview(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    events = []

    def looks_like_event(el):
        a = el.find("a", href=True)
        return a and ("/event" in a["href"] or "/events" in a["href"])

    cards = soup.select("article, .card, .event, .listing, .sv-event, .grid-item, li")
    cards = [c for c in cards if looks_like_event(c)]
    if not cards:
        cards = soup.select("main a[href*='/event'], main a[href*='/events/']")

    for c in cards:
        a = c.find("a", href=True) if hasattr(c, "find") else c
        title = _text(a) if a else _text(c.find("h3") or c.find("h2"))
        href = urljoin(base_url, a["href"]) if a and a.has_attr("href") else base_url

        tnode = c.find("time") if hasattr(c, "find") else None
        start, end = (None, None)
        if tnode and tnode.get("datetime"):
            try:
                start = datetime.fromisoformat(tnode["datetime"].replace("Z", "+00:00"))
            except Exception:
                start, end = parse_datetime_range(_text(tnode))
        else:
            dt_block = c.select_one(".date, .dates, .event-date, .sv-date") if hasattr(c, "select_one") else None
            start, end = parse_datetime_range(_text(dt_block or c))

        location = _text(
            c.select_one(".location, .venue, .sv-venue, .event-venue, .address")
        ) if hasattr(c, "select_one") else ""
        desc = _text(c.select_one(".summary, .description, .teaser, .copy")) if hasattr(c, "select_one") else ""

        if title and start:
            events.append(
                Event(
                    title=title,
                    start=start,
                    end=end,
                    url=href,
                    location=location or None,
                    description=desc or None,
                )
            )
    return events
