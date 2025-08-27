import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime

try:
    from ..normalize import parse_datetime_range, clean_text
    from ..types import Event
except Exception:
    from normalize import parse_datetime_range, clean_text
    from types import Event  # noqa: F401


def _text(el):
    return clean_text(el.get_text(" ", strip=True)) if el else ""


def parse_simpleview(html, base_url):
    """
    Simpleview CMS has a few skins. We support:
    - List articles/cards with <time datetime=...> or date text blocks
    - Detail links usually under <a> with /event or /events/ in href
    """
    soup = BeautifulSoup(html, "lxml")
    events = []

    # Try common card/list containers
    cards = soup.select(
        "article, .card, .event, .listing, .sv-event, .grid-item, li"
    )
    # Keep only ones that look like events (link to /event or /events/)
    def looks_like_event(el):
        a = el.find("a", href=True)
        return a and ("/event" in a["href"] or "/events" in a["href"])

    cards = [c for c in cards if looks_like_event(c)]
    if not cards:
        # fallback: any link rows in the main content area
        cards = soup.select("main a[href*='/event'], main a[href*='/events/']")

    for c in cards:
        a = c.find("a", href=True) if c else None
        title = _text(a) if a else _text(c.find("h3") or c.find("h2"))
        href = urljoin(base_url, a["href"]) if a else base_url

        # Time
        tnode = c.find("time")
        start, end = (None, None)
        if tnode and tnode.get("datetime"):
            try:
                start = datetime.fromisoformat(tnode["datetime"].replace("Z", "+00:00"))
            except Exception:
                start, end = parse_datetime_range(_text(tnode))
        else:
            # look near headings/date spans
            dt_block = c.select_one(".date, .dates, .event-date, .sv-date") or c
            start, end = parse_datetime_range(_text(dt_block))

        # Location / desc (best-effort)
        location = _text(
            c.select_one(".location, .venue, .sv-venue, .event-venue, .address")
        )
        desc = _text(c.select_one(".summary, .description, .teaser, .copy"))

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
