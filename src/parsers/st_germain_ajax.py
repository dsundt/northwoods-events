from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

__all__ = ["parse_st_germain_ajax"]

MONTH_TOKEN = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)(?:[a-z]{0,6})\b"

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _looks_like_title(t: str) -> bool:
    t = (t or "").strip()
    if not t or len(t) < 3:
        return False
    if t.lower() in {"events", "read more", "learn more"}:
        return False
    return True

def _find_date_near(node) -> str:
    # Prefer semantic tags first
    el = node.find("time")
    if el and el.has_attr("datetime"):
        return el["datetime"]
    if el:
        return _text(el)

    for sel in [".date", ".event-date", ".tribe-event-date", ".tribe-event-date-start"]:
        e = node.select_one(sel)
        if e:
            return _text(e)

    # scan surrounding text
    parent = node.find_parent(["article", "li", "div"]) or node
    txt = " ".join([_text(parent), _text(parent.find_next_sibling()), _text(parent.find_previous_sibling())])
    m = re.search(rf"{MONTH_TOKEN}[^|\n]{{0,80}}", txt, re.I)
    return m.group(0).strip() if m else txt.strip()

def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Collect any event-ish anchors living on this page
    anchors = [
        a for a in soup.find_all("a", href=True)
        if ("/events/" in a["href"]) and _looks_like_title(_text(a))
    ]
    seen = set()
    for a in anchors:
        url = urljoin(base_url, a["href"])
        if url in seen:
            continue
        seen.add(url)

        # Grab a proper title (prefer heading around the link)
        title = _text(a)
        head = a.find_parent().find(["h2", "h3"]) if a.find_parent() else None
        if head and _looks_like_title(_text(head)):
            title = _text(head)
        title = re.sub(r"\s+", " ", title).strip()
        if not _looks_like_title(title):
            continue

        # Pull a nearby date string
        start = _find_date_near(a)
        if not start or not re.search(MONTH_TOKEN, start, re.I):
            # if no obvious date, skip (prevents junk)
            continue

        # location (best-effort)
        parent = a.find_parent(["article", "li", "div"]) or a
        loc_el = parent.find(class_=re.compile("location|venue|where", re.I))
        location = _text(loc_el) if loc_el else ""

        items.append({"title": title, "start": start, "url": url, "location": location})

    return items
