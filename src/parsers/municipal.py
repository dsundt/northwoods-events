from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from utils.dates import parse_datetime_range

__all__ = ["parse_municipal"]


# ---------------------------
# Helpers
# ---------------------------

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""


_DEFUSE_HEADERS = {
    "events", "upcoming events", "calendar", "event calendar", "board meetings"
}

# Frequent municipal calendar hints
_DATE_HINTS = (
    "time[datetime]",  # semantic <time datetime="...">
    "time",            # or just <time>
    ".date",
    ".event-date",
    ".ai1ec-event-time",   # All-in-One Event Calendar
    ".ai1ec-event-time-block",
    ".tribe-event-date-start",  # if they run TEC
    ".tribe-event-date",
)

_TITLE_HINTS = (
    ".event-title",
    ".ai1ec-event-title",
    ".tribe-event-title",
    "h3", "h2", "h4",
)


def _maybe_parse(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s or s.lower() in _DEFUSE_HEADERS:
        return None
    try:
        return parse_datetime_range(s)
    except Exception:
        return None


# ---------------------------
# Parser
# ---------------------------

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Defensive municipal calendar parser.

    Supports common WP calendar plugins (AI1EC, The Events Calendar) and simple
    list/table layouts. We favor semantic <time> tags when available and otherwise
    fall back to nearby text that looks like a date/time.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # 1) Obvious event containers: list items, articles, rows with links
    containers = []
    containers.extend(soup.select("li.event, li.ai1ec-event, article.ai1ec_event, article, .event, .ai1ec-event"))
    if not containers:
        # Generic fallback: any container that has a link and some date-ish node
        for el in soup.find_all(["li", "article", "div", "tr"]):
            if el.find("a", href=True) and (el.select_one(",".join(_DATE_HINTS)) or el.find("time")):
                containers.append(el)

    # 2) Calendar table fallback (common on town sites): each cell may contain multiple links
    if not containers:
        for cell in soup.select("table.calendar td, table#calendar td, .calendar td"):
            if cell.find("a", href=True):
                containers.append(cell)

    # de-dup
    seen = set()
    containers = [c for c in containers if id(c) not in seen and not seen.add(id(c))]

    for c in containers:
        # Title
        title = ""
        for sel in _TITLE_HINTS:
            el = c.select_one(sel)
            if el:
                title = _text(el)
                break
        if not title:
            a = c.find("a", href=True)
            title = _text(a) if a else ""
        title = re.sub(r"\s+", " ", (title or "")).strip()
        if not title:
            continue

        # URL
        a = c.find("a", href=True)
        url = urljoin(base_url, a["href"]) if a else base_url

        # Date/time
        dt_text = ""
        # Prefer semantic <time>
        t = c.find("time")
        if t:
            # Use datetime attribute if present; else use visible text
            dt_text = t.get("datetime") or _text(t)

        if not dt_text:
            for sel in _DATE_HINTS:
                el = c.select_one(sel)
                if el:
                    dt_text = _text(el)
                    if dt_text:
                        break

        # last resort: use container text, but avoid pure headings
        if not dt_text or dt_text.lower() in _DEFUSE_HEADERS:
            dt_text = _text(c)

        start_iso = _maybe_parse(dt_text) or _maybe_parse(title)
        if not start_iso:
            # skip items that don't reveal a date/time at all
            continue

        # Location (best-effort)
        location = ""
        loc_el = (
            c.select_one(".location")
            or c.select_one(".event-location")
            or c.find(class_=re.compile(r"(venue|location)", re.I))
        )
        if loc_el:
            location = _text(loc_el).strip()

        items.append(
            {
                "title": title,
                "start": start_iso,
                "url": url,
                "location": location,
            }
        )

    return items
