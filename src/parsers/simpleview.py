from __future__ import annotations
import re
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from utils.dates import parse_datetime_range

__all__ = ["parse_simpleview"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Prefer JSON-LD events if present
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(tag.string or "null")
        except Exception:
            continue
        data = data if isinstance(data, list) else [data]
        for obj in data:
            if not isinstance(obj, dict):
                continue
            if obj.get("@type") == "Event":
                title = obj.get("name") or ""
                start = obj.get("startDate") or obj.get("startTime") or ""
                url = urljoin(base_url, obj.get("url") or "")
                if title and start:
                    items.append({"title": title.strip(), "start": start.strip(), "url": url, "location": _text(None)})

    # If we found events in JSON-LD, return them
    if items:
        return items

    # Otherwise, scrape visible “event-like” links:
    # Many Simpleview DMOs link details under /event/... or /events/slug/ paths
    anchors = [a for a in soup.find_all("a", href=True)
               if re.search(r"/event[s]?/", a["href"], re.I)]
    seen = set()
    for a in anchors:
        url = urljoin(base_url, a["href"])
        if url in seen:
            continue
        seen.add(url)
        title = _text(a).strip()
        if not title:
            continue

        # Try to pick a nearby datetime string
        cont = a.find_parent(["article", "div", "li", "section"]) or a
        dt_text = _text(cont)
        start = None
        try:
            start = parse_datetime_range(dt_text)
        except Exception:
            # leave start None; some DMOs only expose dates on detail pages
            pass

        items.append({
            "title": title,
            "start": start or "",
            "url": url,
            "location": ""
        })

    return items
