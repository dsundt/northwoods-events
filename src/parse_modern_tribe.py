# src/parse_modern_tribe.py
import json
import re
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .fetch import fetch_html
from .utils import norm_event, parse_date, clean_text, save_debug_html


def _rest_events(base_url: str, tzname: str, days_ahead: int = 365) -> List[dict]:
    """
    Try Tribe Events Calendar REST: /wp-json/tribe/events/v1/events
    Not all sites expose this, but when they do it's the most reliable path.
    """
    m = re.match(r"^https?://[^/]+/", base_url)
    if not m:
        return []
    root = m.group(0)
    api = urljoin(root, "wp-json/tribe/events/v1/events")
    params = {
        "start_date": None,
        "end_date": None,
        "per_page": 100,
    }

    # Avoid importing datetime at module top to keep deps minimal here
    import datetime as dt

    start = dt.datetime.utcnow().date()
    end = start + dt.timedelta(days=days_ahead)
    params["start_date"] = start.isoformat()
    params["end_date"] = end.isoformat()

    try:
        r = requests.get(api, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    out: List[dict] = []
    for ev in data.get("events", []):
        venue = ev.get("venue") or {}
        img = ev.get("image") or {}
        out.append(
            norm_event(
                source="Modern Tribe (REST)",
                title=ev.get("title"),
                url=ev.get("url"),
                start=ev.get("start_date"),
                end=ev.get("end_date"),
                tzname=tzname,
                location=clean_text(venue.get("address")),
                city=clean_text(venue.get("city")),
                description=clean_text(ev.get("description")),
                image=img.get("url"),
            )
        )
    return out


def _parse_json_ld(soup: BeautifulSoup, tzname: str, source_name: str, page_url: str) -> List[dict]:
    out: List[dict] = []
    for tag in soup.select('script[type="application/ld+json"]'):
        txt = tag.get_text(strip=True)
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue
        blocks = data if isinstance(data, list) else [data]
        for b in blocks:
            at = b.get("@type")
            is_event = (isinstance(at, str) and at == "Event") or (isinstance(at, list) and "Event" in at)
            if not (isinstance(b, dict) and is_event):
                continue
            loc = b.get("location") or {}
            addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
            image = b.get("image")
            image_url = image[0] if isinstance(image, list) else image
            out.append(
                norm_event(
                    source=source_name,
                    title=b.get("name"),
                    url=b.get("url") or page_url,
                    start=b.get("startDate"),
                    end=b.get("endDate"),
                    tzname=tzname,
                    location=clean_text(loc.get("name")),
                    city=clean_text(addr.get("addressLocality")),
                    description=clean_text(b.get("description")),
                    image=image_url,
                )
            )
    return out


def _parse_cards(soup: BeautifulSoup, tzname: str, source_name: str, page_url: str) -> List[dict]:
    out: List[dict] = []
    # Common TEC card containers
    cards = soup.select(
        ".tribe-events-calendar-list__event, "
        ".tribe-events-calendar-month__calendar-event, "
        ".tec-events .tec-event, "
        ".tribe-events .tribe-common-g-row"
    )
    for c in cards:
        a = c.select_one("a[href]")
        title = clean_text(a.get_text()) if a else None
        href = (a.get("href") if a else None) or page_url
        # date text appears in a variety of spans
        date_el = c.select_one(
            "[data-date], .tribe-events-calendar-list__event-date, "
            ".tec-event__date, time[datetime], .tribe-event-date-start"
        )
        date_txt = clean_text(date_el.get("datetime") if date_el and date_el.has_attr("datetime") else (date_el.get_text() if date_el else None))
        out.append(
            norm_event(
                source=source_name,
                title=title,
                url=href,
                start=parse_date(date_txt, tzname),
                end=None,
                tzname=tzname,
                location=None,
                city=None,
                description=None,
                image=None,
            )
        )
    return out


def parse_modern_tribe(url: str, name: str, tzname: str) -> List[dict]:
    # 1) Prefer REST if available.
    rest = _rest_events(url, tzname)
    if rest:
        return rest

    # 2) Otherwise render the page (Playwright when enabled) and parse.
    html = fetch_html(url, source={"kind": "modern_tribe", "name": name})
    soup = BeautifulSoup(html, "lxml")

    events = []
    events.extend(_parse_json_ld(soup, tzname, name, url))
    if not events:
        events.extend(_parse_cards(soup, tzname, name, url))

    if not events:
        # Save debug HTML so we can adjust selectors next run.
        save_debug_html(name, html)

    return events
