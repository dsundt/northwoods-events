from __future__ import annotations
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import json
from datetime import datetime

__all__ = ["parse_simpleview"]

def _text(el):
    return " ".join(el.stripped_strings) if el else ""

def _parse_date(text):
    # Handles e.g. "Saturday, July 6, 2024" or "Sep 28, 2024"
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s*(\d{4})", text)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
        except Exception:
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date().isoformat()
            except Exception:
                pass
    return ""

def parse_simpleview(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    events = []

    # 1. Try to extract events from embedded JSON-LD (Google/SEO data)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            # Can be a dict or list
            data = json.loads(script.string)
            if isinstance(data, dict):
                graph = data.get("@graph")
                if graph:
                    data = graph
                else:
                    data = [data]
            for ev in data if isinstance(data, list) else []:
                if ev.get("@type") == "Event":
                    title = ev.get("name", "").strip()
                    start = ev.get("startDate", "").strip()
                    url = urljoin(base_url, ev.get("url", "") or base_url)
                    loc = ""
                    locdata = ev.get("location")
                    if isinstance(locdata, dict):
                        loc = locdata.get("name", "") or locdata.get("address", "")
                    if title and start:
                        events.append({
                            "title": title,
                            "start": start,
                            "url": url,
                            "location": loc.strip(),
                        })
        except Exception:
            continue
    if events:
        return events

    # 2. Fall back to HTML scraping for classic event blocks
    event_blocks = soup.find_all(lambda tag: tag.name in ("li", "div") and (tag.find("a") and (tag.find("h3") or tag.find("h2") or tag.find("h4"))))
    for block in event_blocks:
        title = ""
        date_str = ""
        url = ""
        location = ""
        a = block.find("a", href=True)
        if a:
            url = urljoin(base_url, a["href"])
        # Title
        h = block.find(["h2", "h3", "h4"])
        title = _text(h) if h else _text(a)
        if not title or title.lower() in ("events", "annual events", "featured events"):
            continue
        # Date and location are often in sibling <p> or meta tags or in the block
        date_str = ""
        location = ""
        for p in block.find_all("p"):
            if not date_str:
                date_str = _parse_date(p.get_text())
            if not location and "location" in p.get_text().lower():
                location = p.get_text().strip()
        # Try to parse date from title if still missing
        if not date_str:
            date_str = _parse_date(title)
        # Ignore menu/nav items, empty, or annual event headers
        if not url or not date_str:
            continue
        events.append({
            "title": title,
            "start": date_str,
            "url": url,
            "location": location
        })
    return events
