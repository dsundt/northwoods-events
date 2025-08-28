from __future__ import annotations
import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from utils.dates import parse_datetime_range

__all__ = ["parse_growthzone"]

# strict month token – do NOT match "Mar" inside "Market"
M_TOKEN = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE_NEAR = re.compile(rf"\b{M_TOKEN}\b\s+\d{{1,2}}(?:,\s*\d{{4}})?(?:\s*@\s*\d{{1,2}}:\d{{2}}\s*(?:am|pm))?", re.I)
MDY_SLASH = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
MDY_DASH = re.compile(r"\b\d{1,2}-\d{1,2}-\d{2,4}\b")

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _first_date_like(s: str) -> Optional[str]:
    s = s or ""
    for rx in (DATE_NEAR, MDY_SLASH, MDY_DASH):
        m = rx.search(s)
        if m:
            frag = m.group(0)
            # Normalize slash/dash forms to Month Day, Year for parser
            if rx in (MDY_SLASH, MDY_DASH):
                parts = re.split(r"[/-]", frag)
                mm, dd, yy = int(parts[0]), int(parts[1]), int(parts[2])
                if yy < 100:
                    yy += 2000
                try:
                    dt = datetime(yy, mm, dd)
                    return dt.isoformat()
                except Exception:
                    continue
            # month-word form -> feed to parse_datetime_range
            try:
                return parse_datetime_range(frag)
            except Exception:
                continue
    return None

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Target event links; cards often anchor to /events/details/...
    anchors = [a for a in soup.find_all("a", href=True)
               if "/events/details/" in a["href"] or "/events/details" in a["href"]]
    if not anchors:
        anchors = soup.select('[data-ga-category="Events"] a, a.mn-event, .mn-event a, .mn-card a')

    seen = set()
    for a in anchors:
        href = a.get("href", "")
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)

        container = a.find_parent(["article", "li", "div"]) or a
        title = _text(container.find(["h3", "h2"])) or _text(a)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # nearby text to locate a date (avoid "Market" trap by using strict token regex above)
        around = " ".join([
            _text(container),
            _text(container.find_next_sibling()),
            _text(container.find_previous_sibling()),
        ])

        start = _first_date_like(around) or _first_date_like(title)
        if not start:
            # Some calendars put the date in the details URL itself (…-08-23-2025-12345)
            m = re.search(r"(\d{2})-(\d{2})-(\d{4})", url)
            if m:
                mm, dd, yy = map(int, m.groups())
                try:
                    start = datetime(yy, mm, dd).isoformat()
                except Exception:
                    start = None
        if not start:
            # If we still can't find a date, skip (prevents bad records).
            continue

        # Optional location
        loc = ""
        for cls in ("mn-event-location", "mn-location", "location"):
            el = container.select_one(f".{cls}")
            if el:
                loc = _text(el); break

        items.append({"title": title, "start": start, "url": url, "location": loc})

    return items
