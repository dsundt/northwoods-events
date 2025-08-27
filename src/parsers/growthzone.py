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


def parse_growthzone(html, base_url):
    """
    GrowthZone calendar (e.g., business.rhinelanderchamber.com/events/calendar)
    often renders a grid with event popups or inline list rows containing
    anchors to /events/details/.... We’ll scrape those anchors and parse
    the nearest date text or <time>.
    """
    soup = BeautifulSoup(html, "lxml")
    events = []

    # Common: links to /events/details/ or /event/details/
    links = soup.select("a[href*='/events/details/'], a[href*='/event/details/']")
    seen = set()
    for a in links:
        href = urljoin(base_url, a.get("href"))
        if href in seen:
            continue
        seen.add(href)

        title = _text(a) or _text(a.find("span")) or _text(a.parent)
        # Try to find a nearby time element or date text in the same row/card
        parent = a.closest("tr") or a.closest("li") or a.closest("div") or a.parent
        tnode = None
        if parent:
            tnode = parent.find("time") or parent.select_one(".date, .dates, .when")
        start, end = (None, None)
        if tnode and tnode.get("datetime"):
            try:
                start = datetime.fromisoformat(tnode["datetime"].replace("Z", "+00:00"))
            except Exception:
                start, end = parse_datetime_range(_text(tnode))
        else:
            start, end = parse_datetime_range(_text(parent))

        location = _text(parent.select_one(".where, .location, .venue")) if parent else ""
        desc = _text(parent.select_one(".desc, .description, .summary")) if parent else ""

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
