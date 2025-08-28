from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils.dates import parse_date_from_url, parse_date_string, parse_time_string

__all__ = ["parse_growthzone"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _iso(dt_part: str, h: Optional[int] = None, m: Optional[int] = None) -> str:
    date_part = dt_part.split("T")[0]
    hh = h if h is not None else 0
    mm = m if m is not None else 0
    return f"{date_part}T{hh:02d}:{mm:02d}:00"

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # The canonical cards: <a href="/events/details/...">
    anchors = [a for a in soup.find_all("a", href=True) if "/events/details/" in a["href"]]
    if not anchors:
        return items

    for a in anchors:
        href = urljoin(base_url, a["href"])
        title = _text(a) or _text(a.find_parent().find(["h3","h2"])) or ""
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # Prefer date from URL (…-MM-DD-YYYY-…), which GrowthZone provides reliably
        date_from_url = parse_date_from_url(href)

        # Try to enhance with time if available near the anchor
        parent = a.find_parent(["li","article","div"]) or a
        context = _text(parent)
        hm = parse_time_string(context)

        if date_from_url:
            start_iso = _iso(date_from_url, *(hm if hm else (0,0)))
        else:
            # Fallback to a textual month/day nearby (rare)
            d = parse_date_string(context)
            if d:
                if hm:
                    h, m = hm
                    start_iso = f"{d.isoformat()}T{h:02d}:{m:02d}:00"
                else:
                    start_iso = f"{d.isoformat()}T00:00:00"
            else:
                # Give up on this entry
                continue

        # Location (best effort)
        loc = ""
        for cls in ("mn-event-location", "mn-location", "location", "eventLocation"):
            el = parent.select_one(f".{cls}")
            if el:
                loc = _text(el)
                break

        items.append({
            "title": title,
            "start": start_iso,
            "url": href,
            "location": loc,
        })

    return items
