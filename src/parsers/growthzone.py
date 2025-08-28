from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

__all__ = ["parse_growthzone"]

# ---------------------------
# Helpers
# ---------------------------

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""


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

# Matches: "Aug 23, 2025 @ 10:00 am", "August 23 10:00 am", "Aug 23"
_DATETIME_RE = re.compile(
    r"(?P<month>\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*)\s+"
    r"(?P<day>\d{1,2})"
    r"(?:,?\s*(?P<year>\d{4}))?"
    r"(?:\s*(?:@|,)?\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>am|pm))?",
    re.IGNORECASE,
)

def _infer_year(mon: int, day: int, explicit: Optional[int]) -> int:
    if explicit:
        return explicit
    today = date.today()
    candidate = date(today.year, mon, day)
    # If the date is ~last season (more than ~10 months ago), bump a year
    if (candidate - today).days < -300:
        return today.year + 1
    return today.year

def _parse_card_datetime(text: str) -> Optional[str]:
    m = _DATETIME_RE.search(text or "")
    if not m:
        return None
    mon = MONTHS[m.group("month").lower()]
    day = int(m.group("day"))
    year = _infer_year(mon, day, int(m.group("year")) if m.group("year") else None)
    if m.group("hour"):
        h = int(m.group("hour")) % 12
        mi = int(m.group("minute"))
        if m.group("ampm").lower() == "pm":
            h += 12
        dt = datetime(year, mon, day, h, mi)
    else:
        dt = datetime(year, mon, day)
    return dt.isoformat()

@dataclass
class Item:
    title: str
    start: str
    url: str
    location: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"title": self.title, "start": self.start, "url": self.url, "location": self.location}


# ---------------------------
# Parser
# ---------------------------

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Tolerant parser for GrowthZone lists/grids.
    We search anchors that look like event detail links and extract nearby date text.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Item] = []

    # Typical patterns:
    # - data-ga-category="Events"
    # - anchors under .mn-event or .mn-card
    cards = soup.select('[data-ga-category="Events"] a, a.mn-event, .mn-event a, .mn-card a')
    if not cards:
        cards = [a for a in soup.find_all("a", href=True) if "/events/details/" in a["href"]]

    for a in cards:
        url = urljoin(base_url, a.get("href", ""))
        container = a.find_parent(["article", "li", "div"]) or a

        title = _text(a) or _text(container.find(["h3", "h2"]))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # gather nearby text to find a date
        ctx = " ".join(
            filter(None, [
                _text(container),
                _text(container.find_next_sibling()),
                _text(container.find_previous_sibling()),
            ])
        )
        start = _parse_card_datetime(ctx) or _parse_card_datetime(title)
        if not start:
            # As a last resort: skip — we don't emit dateless items
            continue

        # Location (best-effort)
        loc = ""
        for cls in ("mn-event-location", "mn-location", "location"):
            el = container.select_one(f".{cls}")
            if el:
                loc = _text(el).strip()
                break

        items.append(Item(title=title, start=start, url=url, location=loc))

    return [i.to_dict() for i in items]
