from __future__ import annotations
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import re
from datetime import datetime

__all__ = ["parse_municipal"]

DATE_ATTRS = ["datetime", "content", "data-date"]
INLINE_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")  # ISO date present in many municipal calendars

def _text(n) -> str:
    return " ".join(n.stripped_strings) if n else ""

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Look for obvious calendar grid/list items; avoid generic “links” tiles (promos)
    rows = []
    rows += soup.select(".calendar .event, .calendar li, .ai1ec-event, .tribe-events-calendar-list__event")
    if not rows:
        rows = soup.select("li, article")

    for r in rows:
        # Skip items that are clearly external promo tiles (e.g., “Minocqua Area Visitors Bureau” pointing off-site)
        a = r.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if href.startswith("http") and base_url.split("/")[2] not in href:
            # external link tile: only accept if there is a valid date attribute nearby
            if not any(t.get(attr) for attr in DATE_ATTRS for t in r.find_all(True)):
                continue

        title = _text(r.find(["h3","h2"]) or a).strip()
        if not title or title.lower() in {"untitled"}:
            continue

        # Derive date: prefer <time datetime=...> then any ISO-like date found within the row
        dt_iso = None
        t = r.find("time")
        if t:
            for k in DATE_ATTRS:
                if t.has_attr(k):
                    dt_iso = t[k]
                    break
        if not dt_iso:
            m = INLINE_DATE.search(_text(r))
            if m:
                y, mo, d = map(int, m.groups())
                dt_iso = datetime(y, mo, d).isoformat()

        if not dt_iso:
            continue

        items.append({
            "title": title,
            "start": dt_iso,
            "url": urljoin(base_url, href),
            "location": "",
        })

    return items
