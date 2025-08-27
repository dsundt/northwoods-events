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


def parse_growthzone(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    events = []

    links = soup.select("a[href*='/events/details/'], a[href*='/event/details/']")
    seen = set()
    for a in links:
        href = urljoin(base_url, a.get("href"))
        if href in seen:
            continue
        seen.add(href)

        title = _text(a) or _text(a.find("span")) or _text(a.parent)

        parent = a.find_parent("tr") or a.find_parent("li") or a.find_parent("div") or a.parent
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
            start, end = parse_datetime_range(_text(parent or a))

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
