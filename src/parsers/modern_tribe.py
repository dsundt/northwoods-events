import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# Expect helpers from your project:
# - parse_datetime_range(text_or_attrs) -> (dt_start, dt_end or None)
# - clean_text(text) -> str
# - Event(title, start, end, url, location, description)
try:
    from ..normalize import parse_datetime_range, clean_text
    from ..types import Event
except Exception:  # allow running as a script during CI
    from normalize import parse_datetime_range, clean_text
    from types import Event  # noqa: F401  (replace with your real Event import)


def _text(el):
    return clean_text(el.get_text(" ", strip=True)) if el else ""


def _parse_iso_time(node):
    """
    TEC often provides <time datetime="2025-07-04T18:00:00-05:00">.
    Prefer that; else fall back to visible text via parse_datetime_range.
    """
    if not node:
        return None, None

    dt_attr = node.get("datetime")
    if dt_attr:
        # Sometimes TEC provides start + end as two <time> nodes
        # or one node for start and a sibling span for end. We’ll take what we have.
        try:
            start = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
            return start, None
        except Exception:
            pass

    # Fallback to visible text parsing
    return parse_datetime_range(_text(node))


def parse_modern_tribe(html, base_url):
    """
    Handles Modern Tribe / The Events Calendar in 'list' and some theme variants.
    Returns a list[Event].
    """

    soup = BeautifulSoup(html, "lxml")

    # Hard filter: if the page is actually a Google Calendar embed page
    # (seen in Arbor Vitae) that only says "Google Calendar", skip.
    page_title = _text(soup.find("title"))
    if page_title.strip().lower() == "google calendar":
        return []

    events = []

    # Preferred List View (TEC v5+): .tribe-events-calendar-list__event
    list_items = soup.select(".tribe-events-calendar-list__event")
    if not list_items:
        # Older class names (pre v5 or theme overrides)
        list_items = soup.select(
            ".tribe-events-list .type-tribe_events, "
            ".tribe-events-loop .type-tribe_events, "
            "article.tribe-events-calendar-list__event-row"
        )

    # Absolute last-resort: anything that looks like an event card with a TEC link
    if not list_items:
        list_items = soup.select("article, li, div")
        list_items = [el for el in list_items if el.select_one("a[href*='event']")]

    for li in list_items:
        # Title + URL
        a = (
            li.select_one("h3 a, h2 a, .tribe-events-calendar-list__event-title a")
            or li.find("a", href=True)
        )
        title = _text(a) if a else ""
        href = urljoin(base_url, a["href"]) if a and a.has_attr("href") else base_url

        # Skip trash titles like “Google Calendar”
        if title and title.strip().lower() == "google calendar":
            continue

        # Date/Time: prefer <time datetime=...>
        # Try common spots:
        time_node = (
            li.find("time")
            or li.select_one(".tribe-events-calendar-list__event-datetime time")
            or li.select_one(".tribe-event-date-start")
        )
        start, end = _parse_iso_time(time_node)

        # If still nothing, try visible text around the time area
        if not start:
            dt_block = (
                li.select_one(".tribe-events-calendar-list__event-datetime")
                or li.select_one(".tribe-events-event-meta")
                or li
            )
            start, end = parse_datetime_range(_text(dt_block))

        # Location (best-effort)
        location = _text(
            li.select_one(".tribe-events-venue__name, .tribe-venue, .tribe-events-venue")
        )
        # Description (short)
        desc = _text(
            li.select_one(
                ".tribe-events-calendar-list__event-description, .entry-content, .tribe-events-content"
            )
        )

        # Guard: we need at minimum a title and a start
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
