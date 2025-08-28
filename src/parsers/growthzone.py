from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

__all__ = ["parse_growthzone"]

# Strict month→day anchor prevents "Mar" in "Market"
_M = r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b"
DATETIME_RE = re.compile(
    rf"(?P<mon>{_M})\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?(?:\s*@?\s*(?P<h>\d{{1,2}}):(?P<m>\d{{2}})\s*(?P<ampm>am|pm))?",
    re.I
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
    candidate = date(today.year, mon, day)
    if (candidate - today).days < -300:
        return today.year + 1
    return today.year

def _to_24(h: int, m: int, ampm: Optional[str]) -> (int, int):
    if not ampm:
        return h, m
    h = h % 12
    if ampm.lower() == "pm":
        h += 12
    return h, m

def _parse_one_datetime(text: str) -> Optional[str]:
    m = DATETIME_RE.search(text or "")
    if not m:
        return None
    mon = MONTHS[m.group("mon").lower()]
    day = int(m.group("day"))
    year = _infer_year(mon, day, int(m.group("year")) if m.group("year") else None)
    if m.group("h") and m.group("m"):
        h = int(m.group("h")); mm = int(m.group("m"))
        h, mm = _to_24(h, mm, m.group("ampm"))
        return datetime(year, mon, day, h, mm).isoformat()
    return datetime(year, mon, day).isoformat()

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Anchor cards; GrowthZone often uses /events/details/... links
    anchors = [a for a in soup.find_all("a", href=True) if "/events/details/" in a["href"]]
    # Also consider widgets that add data-ga-category="Events"
    anchors.extend(soup.select('[data-ga-category="Events"] a'))

    seen = set()
    for a in anchors:
        href = a.get("href", "")
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)

        # Title: prefer heading text within / next to the anchor
        title = _text(a)
        if not title:
            h = a.find_parent(["article", "div", "li"])
            title = _text(h.find(["h2", "h3"])) if h else ""
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # Context for date/time: parent block + siblings
        cont = a.find_parent(["article", "li", "div"]) or a
        context = " ".join([
            _text(cont),
            _text(cont.find_next_sibling()),
            _text(cont.find_previous_sibling())
        ])
        start = _parse_one_datetime(context) or _parse_one_datetime(title)
        if not start:
            # try mild fallback: scan the whole document text around anchor
            start = _parse_one_datetime(_text(soup))
        if not start:
            # give up on this anchor
            continue

        # Location (best-effort)
        loc = ""
        for cls in ("mn-event-location", "mn-location", "location"):
            el = cont.select_one(f".{cls}")
            if el:
                loc = _text(el)
                break

        items.append({"title": title, "start": start, "url": url, "location": loc})

    return items
