from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

__all__ = ["parse_growthzone"]

# Only allow real month spellings (prevents matching "Market")
MONTH_ALT = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
TIME_TOKEN = r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>am|pm)"
DATE_RE = re.compile(
    rf"(?P<mon>{MONTH_ALT})\b\s+(?P<day>\d{{1,2}})(?:,?\s*(?P<year>\d{{4}}))?(?:\s*@\s*(?P<time>{TIME_TOKEN}))?",
    re.I,
)

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

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

def _parse_one_datetime(s: str) -> Optional[str]:
    m = DATE_RE.search(s or "")
    if not m:
        return None
    mon_key = m.group("mon").lower()
    if mon_key not in MONTHS:
        return None
    mon = MONTHS[mon_key]
    day = int(m.group("day"))
    year = _infer_year(mon, day, int(m.group("year")) if m.group("year") else None)
    if m.group("time"):
        h = int(m.group("h")); mm = int(m.group("m")); ap = m.group("ampm").lower()
        h = (h % 12) + (12 if ap == "pm" else 0)
        dt = datetime(year, mon, day, h, mm)
    else:
        dt = datetime(year, mon, day)
    return dt.isoformat()

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    anchors = soup.select('[data-ga-category="Events"] a, a.mn-event, .mn-event a, .mn-card a')
    if not anchors:
        anchors = [a for a in soup.find_all("a", href=True) if "/events/details/" in a["href"]]

    seen = set()
    for a in anchors:
        href = a.get("href", "")
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)

        container = a.find_parent(["article", "li", "div"]) or a
        title = _text(a) or _text(container.find(["h3", "h2"])) or _text(container)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or title.lower() in {"events", "calendar", "learn more"}:
            continue

        context_text = " ".join(
            [_text(container), _text(container.find_next_sibling()), _text(container.find_previous_sibling())]
        )
        start = _parse_one_datetime(context_text) or _parse_one_datetime(title)
        if not start:
            # Look inside time/small elements
            near = container.find(["time", "small", "strong", "span"])
            start = _parse_one_datetime(_text(near)) if near else None
        if not start:
            # give up on this card if no valid date
            continue

        loc = ""
        for cls in ("mn-event-location", "mn-location", "location", "venue"):
            el = container.select_one(f".{cls}")
            if el:
                loc = _text(el)
                break

        items.append({"title": title, "start": start, "url": url, "location": loc})

    return items
