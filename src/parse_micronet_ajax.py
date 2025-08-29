from __future__ import annotations
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def parse_micronet_ajax(html: str, base_url: str):
    soup = BeautifulSoup(html, "lxml")
    out = []

    # Try common containers Micronet injects (varies by site theme)
    containers = soup.select(".event-list, .events-list, #events-list, .mn-event-list, .micronet-events, .event-calendar, #event-calendar")
    if not containers:
        # fall back to scan links that look like event detail pages
        for a in soup.select('a[href*="/event/"], a[href*="EventDetails"]'):
            title = (a.get_text(" ", strip=True) or "").strip()
            href = urljoin(base_url, a.get("href", ""))
            if title:
                out.append({"title": title, "start": "", "url": href, "location": ""})
        # return early; DOM likely not hydrated without Playwright
        return out[:200]

    for root in containers:
        for a in root.select('a[href]'):
            title = (a.get_text(" ", strip=True) or "").strip()
            href = urljoin(base_url, a.get("href", ""))
            if not title or not href:
                continue
            # Avoid nav/placeholder
            if title.lower() in ("events", "events |", "learn more", "read more", "details"):
                continue
            out.append({
                "title": title,
                "start": "",
                "url": href,
                "location": "",
            })

    # Dedup
    seen = set(); uniq = []
    for ev in out:
        if ev["url"] in seen: 
            continue
        seen.add(ev["url"])
        uniq.append(ev)

    return uniq[:200]
