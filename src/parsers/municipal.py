from __future__ import annotations
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from utils.dates import parse_datetime_range

__all__ = ["parse_municipal"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Strategy:
    # 1) <time datetime="...">
    for ev in soup.find_all(["article", "li", "div", "tr"]):
        time_tag = ev.find("time", attrs={"datetime": True})
        if not time_tag:
            continue
        start = (time_tag.get("datetime") or "").strip()
        if not start:
            continue
        a = ev.find("a", href=True)
        title = _text(ev.find(["h3", "h2"])) or (a.get_text(strip=True) if a else "")
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        items.append({"title": title, "start": start, "url": urljoin(base_url, a["href"]) if a else base_url, "location": ""})

    if items:
        return items

    # 2) FullCalendar/table-style listings: a row with a date cell & an anchor title
    rows = soup.select("table tr")
    for tr in rows:
        title_a = tr.find("a", href=True)
        if not title_a:
            continue
        title = _text(title_a)
        row_text = _text(tr)
        start = None
        try:
            start = parse_datetime_range(row_text)
        except Exception:
            start = None
        if not start:
            continue
        items.append({"title": title, "start": start, "url": urljoin(base_url, title_a["href"]), "location": ""})

    return items
