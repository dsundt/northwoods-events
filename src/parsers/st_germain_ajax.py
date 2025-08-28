from __future__ import annotations
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

__all__ = ["parse_st_germain_ajax"]

# Capture dates like "Monday, September 1st, 2025" with optional ordinal
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
ORD   = r"(?:st|nd|rd|th)"
DATE_LONG = re.compile(rf"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,\s+({MONTH})\s+(\d{{1,2}})(?:{ORD})?,\s+(\d{{4}})\b", re.I)

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}

def _text(n) -> str:
    return " ".join(n.stripped_strings) if n else ""

def _to_iso(month: int, day: int, year: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}T00:00:00-05:00"

def _parse_date_blob(t: str) -> str | None:
    m = DATE_LONG.search(t or "")
    if not m:
        return None
    mon = MONTHS[m.group(1).lower()]
    day = int(m.group(2))
    year = int(m.group(3))
    return _to_iso(mon, day, year)

def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Their site often loads via admin-ajax; snapshots may contain server-rendered fallback
    blocks that look like cards with an <a> and nearby text including the long date.
    We avoid concatenating every sibling’s text; we take tight scopes only.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Tight card targets: look for obvious event links inside list/card wrappers
    # (The previous issue happened by reading a whole container’s text at once.)
    cards = []
    cards += soup.select("article, .event, .events-list li, .tribe-events-calendar-list__event, .et_pb_post")
    if not cards:
        # fallback to any links in the main content area pointing to /events/
        for a in soup.select("main a[href*='/events/']"):
            cards.append(a.find_parent(["li","article","div"]) or a)

    seen = set()
    for c in cards:
        a = c.find("a", href=True)
        if not a:
            continue
        url = urljoin(base_url, a["href"])
        if url in seen:
            continue
        seen.add(url)

        # Title: just the anchor’s text or a heading — do NOT concatenate entire card text
        title = _text(a) or _text(c.find(["h3","h2"])).strip()
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # Date: search in small radius (link’s parent and immediate siblings)
        local_blobs = [
            _text(a.parent),
            _text(c.find(class_=re.compile("date|when|time", re.I))),
            _text(c.find_next_sibling()),
            _text(c.find_previous_sibling()),
        ]
        start = None
        for blob in local_blobs:
            start = start or _parse_date_blob(blob)
        # As a last resort, scan the card’s text (bounded) for a long date
        start = start or _parse_date_blob(_text(c))
        if not start:
            continue

        items.append({"title": title, "start": start, "url": url, "location": ""})

    return items
