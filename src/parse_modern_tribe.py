# src/parse_modern_tribe.py
import re
from bs4 import BeautifulSoup
from .fetch import fetch_text
from .normalize import normalize_event, parse_dt  # existing utilities

DATE_ONLY = re.compile(
    r"""^(
        (Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\w+\s+\d{1,2},\s+\d{4} |  # e.g., Fri August 30, 2025
        \w+\s+\d{1,2},\s+\d{4} |                                # e.g., August 30, 2025
        \d{1,2}/\d{1,2}/\d{2,4}$                                # e.g., 8/30/25 or 08/30/2025
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

def parse_modern_tribe(source_name: str, url: str, tzname: str | None = None):
    html = fetch_text(url=url, use_playwright=True)
    soup = BeautifulSoup(html, "lxml")

    # this selector is intentionally permissive; keep your existing one if different
    items = soup.select(".tribe-events-calendar-list__event, .tribe-event, .type-tribe_events")

    for it in items:
        # title candidates
        title_el = it.select_one("a.tribe-event-url, a.tribe-events-calendar-list__event-title-link, h3 a, h3")
        title = (title_el.get_text(strip=True) if title_el else "").strip()

        # FILTER: skip date-only headings
        if title and DATE_ONLY.match(title):
            continue

        # parse date/time (keep your existing logic if already solid)
        dt_el = it.select_one("time.tribe-events-calendar-list__event-datetime, time[datetime]")
        start_dt = parse_dt(dt_el.get("datetime")) if dt_el and dt_el.has_attr("datetime") else None

        loc_el = it.select_one(".tribe-events-calendar-list__event-venue, .tribe-venue, .tribe-events-venue-details")
        location = loc_el.get_text(" ", strip=True) if loc_el else None

        href_el = it.select_one("a.tribe-event-url, a.tribe-events-calendar-list__event-title-link")
        href = href_el["href"] if href_el and href_el.has_attr("href") else url

        ev = normalize_event(
            title=title or "(untitled)",
            start=start_dt,
            end=None,
            location=location,
            source=source_name,
            url=href,
            tzname=tzname,
        )
        if ev:
            yield ev
