from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils.dates import parse_datetime_range, combine_date_and_time

__all__ = ["parse_modern_tribe"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

BAD_TITLE = {"recurring", "view all", "view calendar"}

def _pick_title_anchor(card) -> Optional[Dict[str, str]]:
    anchors = card.select(
        ".tribe-events-calendar-list__event-title a, .tribe-events-event-title a, h3 a, h2 a"
    ) or card.select("a")
    chosen = None
    for a in anchors:
        href = a.get("href") or ""
        txt = a.get_text(strip=True)
        if not txt or txt.lower() in BAD_TITLE:
            continue
        if "/event/" in href and not href.endswith("/all/"):
            chosen = a
            break
        if chosen is None:
            chosen = a
    if not chosen:
        return None
    return {"title": chosen.get_text(strip=True), "href": chosen.get("href", "")}

def _pick_date_time(card) -> Optional[str]:
    # Only use <time datetime=...> when datetime *is* a date (YYYY-MM-DD...)
    t = card.find("time", attrs={"datetime": True})
    if t and t["datetime"]:
        date_attr = t["datetime"]
        # Must match a full date, not just a time string
        if re.match(r"^\d{4}-\d{2}-\d{2}", date_attr):
            time_text = t.get_text(" ", strip=True)
            iso = combine_date_and_time(date_attr, time_text)
            if iso:
                return iso

    # Fallback: look for the first string in card text that parses as a full date (and, optionally, time)
    body = _text(card)
    try:
        return parse_datetime_range(body)
    except Exception:
        pass

    # Try title string as last-ditch
    t_anchor = _pick_title_anchor(card)
    if t_anchor:
        try:
            return parse_datetime_range(t_anchor["title"])
        except Exception:
            pass

    return None

def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    cards = soup.select(
        "article.tribe-events-calendar-list__event, .tribe-events-calendar-list__event, .tribe-events-event-card, article"
    )
    if not cards:
        cards = soup.select("li.tribe-events-list-event, .tribe-common-g-row")

    for c in cards:
        title_info = _pick_title_anchor(c)
        if not title_info:
            continue
        title = title_info["title"]
        href = urljoin(base_url, title_info["href"])

        start_iso = _pick_date_time(c)
        if not start_iso:
            continue

        loc_el = c.find(class_=re.compile(r"(venue|location|address)", re.I))
        location = _text(loc_el) if loc_el else ""

        items.append({
            "title": title,
            "start": start_iso,
            "url": href,
            "location": location,
        })

    return items
