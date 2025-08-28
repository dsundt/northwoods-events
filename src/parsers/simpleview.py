from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

__all__ = ["parse_simpleview"]

MONTH_TOKEN = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)(?:[a-z]{0,6})\b"

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _looks_like_title(t: str) -> bool:
    t = (t or "").strip()
    if not t or len(t) < 3:
        return False
    if t.lower() in {"events", "calendar", "learn more", "read more"}:
        return False
    return True

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # 1) Try known card/list containers
    cards = soup.select(
        ".event, .event-card, .event-list-item, .card.event, .listing, article, li"
    )

    # 2) Also consider anchors that clearly point to event pages
    event_anchors = [a for a in soup.find_all("a", href=True)
                     if ("/event" in a["href"] or "/events/" in a["href"]) and _looks_like_title(_text(a))]

    # Normalize to unified “blocks”: prefer cards; else use anchor parents
    blocks = cards[:]
    if not blocks and event_anchors:
        blocks = [a.find_parent(["article", "li", "div"]) or a for a in event_anchors]

    seen = set()
    for b in blocks:
        a = b.find("a", href=True)
        if not a:
            continue
        url = urljoin(base_url, a["href"])
        if url in seen:
            continue
        seen.add(url)

        title = _text(b.find(["h2", "h3"])) or _text(a)
        title = re.sub(r"\s+", " ", title).strip()
        if not _looks_like_title(title):
            continue

        # Date text
        dt = ""
        for sel in ["time", ".date", ".event-date", ".dates", ".event__date", ".card-date"]:
            el = b.select_one(sel)
            if el:
                dt = el["datetime"] if el.name == "time" and el.has_attr("datetime") else _text(el)
                break
        if not dt:
            dt = _text(b)

        if not re.search(MONTH_TOKEN, dt, re.I) and not (b.find("time") and b.find("time").has_attr("datetime")):
            continue

        loc_el = b.find(class_=re.compile("location|venue|where", re.I))
        location = _text(loc_el) if loc_el else ""

        items.append({"title": title, "start": dt.strip(), "url": url, "location": location})

    return items
