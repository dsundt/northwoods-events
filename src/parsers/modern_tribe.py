from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from utils.dates import parse_datetime_range

__all__ = ["parse_modern_tribe"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

# Try to recover a date from URLs like .../2025-10-04/ at the end
_TAIL_DATE = re.compile(r"/(\d{4})-(\d{2})-(\d{2})(?:/)?$")

def _date_from_url(url: str) -> Optional[str]:
    m = _TAIL_DATE.search(url or "")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y:04d}-{mo:02d}-{d:02d}T00:00:00"

# Headings to ignore (“Events”, etc.)
_DEFUSE = {"events", "upcoming events", "featured events"}

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")

    # Cards typically live in articles; also support list card classes
    cards = soup.select("article, .tribe-events-calendar-list__event, .tribe-events-event-card")
    if not cards:
        cards = soup.select(".tribe-common-g-row, li.tribe-events-list-event")

    items: List[Dict[str, Any]] = []

    for c in cards:
        # URL + Title (prefer the inner heading anchor)
        a = c.select_one("h3 a, h2 a, .tribe-events-calendar-list__event-title a") or c.find("a", href=True)
        if not a or not a.get("href"):
            continue
        url = urljoin(base_url, a["href"])
        title = _text(a) or _text(c.find(["h3", "h2"]))
        title = re.sub(r"\s+", " ", title).strip()
        if not title or title.lower() in _DEFUSE:
            continue

        # Date/time:
        # 1) semantic <time datetime="...">
        ttag = c.find("time", attrs={"datetime": True})
        start_iso: Optional[str] = ttag["datetime"] if ttag else None

        # 2) Common date/time containers
        dt_bits = [
            _text(c.select_one(".tribe-event-date-start")),
            _text(c.select_one(".tribe-event-date")),
            _text(c.select_one(".tribe-events-calendar-list__event-date")),
            _text(c),
        ]
        if (not start_iso) or start_iso.strip() == "":
            for chunk in dt_bits:
                chunk = (chunk or "").strip()
                if not chunk or chunk.lower() in _DEFUSE:
                    continue
                try:
                    start_iso = parse_datetime_range(chunk)
                    break
                except Exception:
                    continue

        # 3) Fallback from URL (recurrence URLs often end /YYYY-MM-DD/)
        if not start_iso:
            start_iso = _date_from_url(url)

        if not start_iso:
            # If we truly cannot parse a date, skip this container row
            continue

        # Location (best effort)
        loc_el = c.find(class_=re.compile(r"(venue|location)", re.I))
        location = _text(loc_el)

        items.append({
            "title": title,
            "start": start_iso,
            "url": url,
            "location": location,
        })

    return items
