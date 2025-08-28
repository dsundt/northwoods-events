from __future__ import annotations
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from utils.dates import combine_date_and_time, parse_datetime_range

__all__ = ["parse_municipal"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Typical WP calendar markup: entries with <time datetime="YYYY-MM-DD">
    for e in soup.select("article, li, .event, .tribe-events-calendar-list__event"):
        a = e.find("a", href=True)
        title = _text(e.find(["h3","h2"])) or (a.get_text(strip=True) if a else "")
        if not title:
            continue

        t = e.find("time", attrs={"datetime": True})
        start_iso = ""
        if t:
            start_iso = combine_date_and_time(t.get("datetime",""), t.get_text(" ", strip=True))
        if not start_iso:
            try:
                start_iso = parse_datetime_range(_text(e))
            except Exception:
                start_iso = ""

        items.append({
            "title": title,
            "start": start_iso,
            "url": urljoin(base_url, a["href"]) if a else base_url,
            "location": _text(e.find(class_=re.compile("location|venue", re.I))) or "",
        })

    return items
