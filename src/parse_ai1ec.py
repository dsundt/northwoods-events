# src/parse_ai1ec.py
from __future__ import annotations
from bs4 import BeautifulSoup
from typing import List, Dict

def parse_ai1ec(html: str) -> List[Dict]:
    """
    Parse events from All-in-One Event Calendar (Ai1EC).
    Supports common classes: .ai1ec-event-instance, .ai1ec-agenda-event, .ai1ec-event-summary.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    items: List[Dict] = []

    candidates = soup.select(
        ".ai1ec-event, "
        ".ai1ec-event-instance, "
        ".ai1ec-agenda-event, "
        "article.ai1ec_event, "
        ".ai1ec-event-container, "
        ".ai1ec-event-summary"
    )

    for node in candidates:
        # Title + link
        title_el = node.select_one(".ai1ec-event-title, h3 a, a")
        title = title_el.get_text(strip=True) if title_el else ""
        url = title_el["href"] if title_el and title_el.has_attr("href") else ""

        # Date/time text
        date_el = node.select_one(".ai1ec-event-time, time, .ai1ec-date, .ai1ec-time")
        date_text = date_el.get_text(" ", strip=True) if date_el else ""

        # Venue
        venue_el = node.select_one(".ai1ec-location, .venue, .ai1ec-venue")
        venue_text = venue_el.get_text(" ", strip=True) if venue_el else ""

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
