from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

__all__ = ["parse_growthzone"]

# Explicit month tokens (prevents capturing "Market")
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

# Use anchored alternations, not "[a-z]*" after month
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_TIME  = r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>am|pm)"
DATE_RE = re.compile(
    rf"\b(?P<mon>{_MONTH})\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?(?:\s*@\s*(?P<stime>{_TIME}))?\b",
    re.I,
)

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _infer_year(mon: int, day: int, year: Optional[int]) -> int:
    if year:
        return year
    today = date.today()
    cand = date(today.year, mon, day)
    if (cand - today).days < -300:
        return today.year + 1
    return today.year

def _parse_one_datetime(text: str) -> Optional[str]:
    if not text:
        return None
    m = DATE_RE.search(text)
    if not m:
        return None
    mon = MONTHS[m.group("mon").lower()]
    day = int(m.group("day"))
    year = _infer_year(mon, day, int(m.group("year")) if m.group("year") else None)
    if m.group("stime"):
        h = int(m.group("h")); mm = int(m.group("m")); ap = m.group("ampm").lower()
        h = (h % 12) + (12 if ap == "pm" else 0)
        dt = datetime(year, mon, day, h, mm)
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

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Item] = []

    # Common GrowthZone structures: cards and rows that link to /events/details/
    anchors = [a for a in soup.find_all("a", href=True) if "/events/details/" in a["href"]]
    # Fallback: trackables (data-ga-category="Events")
    anchors += soup.select('[data-ga-category="Events"] a')

    seen_urls = set()
    for a in anchors:
        url = urljoin(base_url, a["href"])
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Title: prefer the anchor title text; if it's just whitespace, look up to the nearest heading
        title = _text(a).strip()
        if not title:
            parent = a.find_parent(["article", "li", "div"])
            title = _text(parent.find(["h3", "h2"])) if parent else ""
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # Context near the anchor for the date string
        container = a.find_parent(["article", "li", "div"]) or a
        context_text = " ".join([
            _text(container),
            _text(container.find_next_sibling()),
            _text(container.find_previous_sibling()),
        ])

        start = _parse_one_datetime(context_text) or _parse_one_datetime(title)
        if not start:
            # If no date was parseable, skip this — it’s likely a navigation/marketing link.
            continue

        # Location (best-effort)
        location = ""
        for cls in ("mn-event-location", "mn-location", "location"):
            el = container.select_one(f".{cls}")
            if el:
                location = _text(el)
                break

        items.append(Item(title=title, start=start, url=url, location=location))

    return [i.to_dict() for i in items]
