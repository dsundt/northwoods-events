# src/parse_ai1ec.py
from __future__ import annotations
from bs4 import BeautifulSoup
from typing import List, Dict

def parse_ai1ec(html: str) -> List[Dict]:
    """
    Parse events from All-in-One Event Calendar (Ai1EC).
    Handles common Ai1EC classes like .ai1ec-event-instance, .ai1ec-agenda-event.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    items: List[Dict] = []

    candidates = soup.select(
        ".ai1ec-event, .ai1ec-event-instance, "
        ".ai1ec-agenda-event, article.ai1ec_event"
    )
    for node in candidates:
        title_el = node.select_one(".ai1ec-event-title, a")
        title = title_el.get_text(strip=True) if title_el else ""
        url = title_el["href"] if title_el and title_el.has_attr("href") else ""

        date_el = node.select_one(".ai1ec-event-time, time, .ai1ec-date")
        date_text = date_el.get_text(" ", strip=True) if date_el else ""

        venue_el = node.select_one(".ai1ec-location, .venue, .ai1ec-venue")
        venue = venue_el.get_text(" ", strip=True) if venue_el else ""

        if title:
            items.append({
                "title": title,
                "url": url,
                "date_text": date_text,
                "venue_text": venue,
                "iso_datetime": "",
                "iso_end": "",
            })
    return items
