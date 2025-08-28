from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse
from typing import Any, Dict, List

from bs4 import BeautifulSoup

__all__ = ["parse_municipal"]

MONTH_TOKEN = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)(?:[a-z]{0,6})\b"

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _same_host(url: str, base: str) -> bool:
    try:
        return urlparse(url).netloc in ("", urlparse(base).netloc)
    except Exception:
        return True

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    blocks = soup.select("article, .wp-block-post, .event, .calendar-item, table tr, li")
    for b in blocks:
        a = b.find("a", href=True)
        if not a:
            continue
        url = urljoin(base_url, a["href"])
        if not _same_host(url, base_url):
            # skip obvious external promos
            continue

        title = _text(b.find(["h2", "h3"])) or _text(a)
        title = re.sub(r"\s+", " ", (title or "")).strip()
        if not title or title.lower() in {"events", "calendar"}:
            continue

        # Date candidates
        dt = ""
        t = b.find("time")
        if t and t.has_attr("datetime"):
            dt = t["datetime"]
        elif t:
            dt = _text(t)
        if not dt:
            cand = b.find(class_=re.compile("date|time", re.I))
            dt = _text(cand)
        if not dt:
            dt = _text(b)

        if not dt or (not re.search(MONTH_TOKEN, dt, re.I) and not (t and t.has_attr("datetime"))):
            continue

        loc_el = b.find(class_=re.compile("location|venue|where", re.I))
        location = _text(loc_el) if loc_el else ""

        items.append({"title": title, "start": dt.strip(), "url": url, "location": location})

    return items
