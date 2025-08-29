from __future__ import annotations
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def parse_simpleview(html: str, base_url: str):
    soup = BeautifulSoup(html, "lxml")

    out = []
    # Common Simpleview patterns:
    # 1) Cards with class names like "event-card", "listing", or within a grid/list
    for a in soup.select('a[href*="/event/"], a[href*="/events/"]'):
        title = (a.get_text(" ", strip=True) or "").strip()
        href = urljoin(base_url, a.get("href", ""))
        if not title:
            continue
        # Heuristics to avoid nav links
        if title.lower() in ("events", "events |", "here", "learn more", "read more"):
            continue
        out.append({
            "title": title,
            "start": "",         # times are often on detail pages; leave empty
            "url": href,
            "location": "",
        })

    # Deduplicate by URL
    seen = set()
    uniq = []
    for ev in out:
        u = ev["url"]
        if u in seen: 
            continue
        seen.add(u)
        uniq.append(ev)

    return uniq[:200]
