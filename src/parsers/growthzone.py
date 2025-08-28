from __future__ import annotations
import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

__all__ = ["parse_growthzone"]

# Strict month word boundary (prevents matching 'Mar' inside 'Market')
_MWORD = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
_M = rf"\b{_MWORD}\b"
TIME = r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>am|pm)"
DT_RE = re.compile(
    rf"(?P<mon>{_M})\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?"
    rf"(?:\s*(?:@|,)?\s*(?P<stime>{TIME}))?",
    re.I,
)

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _infer_year(mon: int, day: int, explicit: Optional[int]) -> int:
    if explicit:
        return explicit
    today = date.today()
    cand = date(today.year, mon, day)
    if (cand - today).days < -300:
        return today.year + 1
    return today.year

def _parse_one_datetime(s: str) -> Optional[str]:
    m = DT_RE.search(s or "")
    if not m:
        return None
    mon = MONTHS[m.group("mon").lower()]
    day = int(m.group("day"))
    year = _infer_year(mon, day, int(m.group("year")) if m.group("year") else None)
    if m.group("stime"):
        h = int(m.group("h")); mm = int(m.group("m")); ampm = m.group("ampm").lower()
        h = (h % 12) + (12 if ampm == "pm" else 0)
        return datetime(year, mon, day, h, mm).isoformat()
    return datetime(year, mon, day).isoformat()

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # GrowthZone calendars typically render event tiles linking to /events/details/...
    anchors = [a for a in soup.find_all("a", href=True) if "/events/details/" in a["href"]]
    if not anchors:
        # Some skins use data-ga-category=Events
        anchors = soup.select('[data-ga-category="Events"] a')

    for a in anchors:
        url = urljoin(base_url, a["href"])
        # Title: prefer immediate heading text inside the anchor or its child heading
        title = _text(a.find(["h2", "h3"])) or _text(a)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # Look around the tile for a date line
        container = a.find_parent(["article", "li", "div"]) or a
        ctxt = " ".join(
            filter(None, [
                _text(container),
                _text(container.find_next_sibling()),
                _text(container.find_previous_sibling()),
            ])
        )
        start = _parse_one_datetime(ctxt) or _parse_one_datetime(title)
        if not start:
            # If nothing looks like a date, skip this link (likely non-event nav)
            continue

        # Optional location
        loc = ""
        for cls in ("mn-event-location", "mn-location", "location"):
            el = container.select_one(f".{cls}")
            if el:
                loc = _text(el)
                break

        items.append({"title": title, "start": start, "url": url, "location": loc})

    return items
