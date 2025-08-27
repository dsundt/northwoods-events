import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup

try:
    from ..normalize import parse_datetime_range, clean_text
    from ..types import Event
except Exception:
    from normalize import parse_datetime_range, clean_text  # type: ignore
    from types import Event  # type: ignore


def _text(el):
    return clean_text(el.get_text(" ", strip=True)) if el else ""


def _parse_iso_time(node):
    if not node:
        return None, None
    dt_attr = node.get("datetime")
    if dt_attr:
        try:
            start = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
            return start, None
        except Exception:
            pass
    return parse_datetime_range(_text(node))


def parse_modern_tribe(html, base_url):
    """
    The Events Calendar (Modern Tribe) list/grid variants.
    """
    soup = BeautifulSoup(html, "lxml")

    page_title = _text(soup.find("title"))
    if page_title.strip().lower() == "google calendar":
        return []

    events = []

    list_items = soup.select(".tribe-events-calendar-list__event")
    if not list_items:
        list_items = soup.select(
            ".tribe-events-list .type-tribe_events, "
            ".tribe-events-loop .type-tribe_events, "
            "article.tribe-events-calendar-list__event-row"
        )
    if not list_items:
        # very loose fallback
        list_items = [
            el for el in soup.select("article, li, div")
            if el.select_one("a[href*='event']")
        ]

    for li in list_items:
        a = (
            li.select_one("h3 a, h2 a, .tribe-events-calendar-list__event-title a")
            or li.find("a", href=True)
        )
        title = _text(a) if a else ""
        href = urljoin(base_url, a["href"]) if a and a.has_attr("href") else base_url
        if title and title.strip().lower() == "google calendar":
            continue

        time_node = (
            li.find("time")
            or li.select_one(".tribe-events-calendar-list__event-datetime time")
            or li.select_one(".tribe-event-date-start")
        )
        start, end = _parse_iso_time(time_node)

        if not start:
            dt_block = (
                li.select_one(".tribe-events-calendar-list__event-datetime")
                or li.select_one(".tribe-events-event-meta")
                or li
            )
            start, end = parse_datetime_range(_text(dt_block))

        location = _text(
            li.select_one(".tribe-events-venue__name, .tribe-venue, .tribe-events-venue")
        )
        desc = _text(
            li.select_one(
                ".tribe-events-calendar-list__event-description, .entry-content, .tribe-events-content"
            )
        )

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
