# src/parse_ai1ec.py
from __future__ import annotations
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

def parse_ai1ec(html: str) -> List[Dict]:
    """
    Extracts events from All-in-One Event Calendar (Ai1EC)-style markup.
    Returns rows with: title, url, date_text, venue_text, iso_datetime, iso_end
    (date_text is parsed later by your normalize.parse_datetime_range)
    """
    soup = BeautifulSoup(html or "", "html.parser")
    items = []

    # Common Ai1EC selectors
    candidates = soup.select(".ai1ec-event, .ai1ec-event-instance, .ai1ec-agenda-event, .ai1ec-event-card")
    if not candidates:
        # Fallback: look for generic event summaries
        candidates = soup.select(".event, .events-list article, article.type-ai1ec_event")

    for node in candidates:
        title = ""
        url = ""
        date_text = ""
        venue_text = ""

        # Title + URL
        a = node.select_one("a.ai1ec-event-title, h3 a, .entry-title a, a")
        if a:
            title = (a.get_text(strip=True) or "").strip()
            url = (a.get("href") or "").strip()

        # Date text often in .ai1ec-event-time, .ai1ec-time, or meta spans
        dt = node.select_one(".ai1ec-event-time, .ai1ec-time, time, .event-date, .ai1ec-date")
        if dt:
            date_text = dt.get_text(" ", strip=True).strip()

        # Venue
        venue = node.select_one(".ai1ec-location, .venue, .event-venue, .ai1ec-venue")
        if venue:
            venue_text = venue.get_text(" ", strip=True).strip()

        if title:
            items.append({
                "title": title,
                "url": url,
                "date_text": date_text,
                "venue_text": venue_text,
                "iso_datetime": "",
                "iso_end": "",
            })
    return items
