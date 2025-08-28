# src/parsers/modern_tribe.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from utils.text import _text
from utils.dates import parse_datetime_range  # your existing helper


def _first(soup: Tag, selectors: List[str]) -> Optional[Tag]:
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return node
    return None


def _all(soup: Tag, selectors: List[str]) -> List[Tag]:
    out: List[Tag] = []
    for sel in selectors:
        out.extend(soup.select(sel))
    # preserve document order & de-dup
    seen = set()
    uniq: List[Tag] = []
    for n in out:
        if id(n) in seen:
            continue
        seen.add(id(n))
        uniq.append(n)
    return uniq


def _prefer_times(block: Tag) -> Optional[Tuple[str, Optional[str]]]:
    """
    Return (start_iso, end_iso?) if Modern Tribe has <time datetime="..."> nodes.
    """
    times = block.select("time[datetime]")
    if not times:
        return None

    # pick first as start; if a second exists and is later, treat as end
    start = times[0].get("datetime", "").strip()
    end = None
    if len(times) > 1:
        end = times[1].get("datetime", "").strip() or None

    # normalize empty strings to None
    start = start or None
    end = end or None
    if not start:
        return None
    return (start, end)


def _extract_dt_text(block: Tag) -> str:
    """
    Pull a concise date/time text from common Modern Tribe containers.
    We keep this narrow so we don't accidentally hand the *entire page* to the parser.
    """
    dt = _first(
        block,
        [
            # v5 list view
            ".tribe-events-calendar-list__event-datetime",
            ".tribe-events-calendar-list__event-date-tag",
            ".tribe-events-c-small-cta__date",
            # generic
            ".tribe-event-date-start",
            ".tribe-event-date",
            ".tribe-events-meta-group-details",
            ".tribe-events-list-event-date",
        ],
    )
    txt = _text(dt) if dt else _text(block)
    # Common pattern on MT sites: "August 30 @ 6:30 pm - 8:30 pm"
    # The '@' confuses some parsers; make it explicit spacing.
    return txt.replace("@", " ").strip()


def _extract_title_url(block: Tag, base_url: str) -> Tuple[str, Optional[str]]:
    a = _first(
        block,
        [
            "a.tribe-events-calendar-list__event-title-link",
            ".tribe-event-url",
            "h3 a",
            "h2 a",
            "header a",
            "a.tribe-events-event-title",
            "a",
        ],
    )
    if not a:
        title = _text(_first(block, ["h3", "h2"]) or block)
        return (title, None)

    title = _text(a)
    href = a.get("href")
    url = urljoin(base_url, href) if href else None
    return (title, url)


def _extract_location(block: Tag) -> str:
    loc = _first(
        block,
        [
            ".tribe-events-venue",
            ".tribe-events-venue__name",
            ".tribe-events-event-venue",
            ".tribe-events-venue-details",
            ".tribe-events-event-meta .tribe-venue",
            ".tribe-events-address",
        ],
    )
    return _text(loc) if loc else ""


def parse_modern_tribe(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Robust Modern Tribe parser for list views.

    Key fixes vs earlier version:
    - Only parse per-event blocks (no more giving the whole page ‘Events ...’ to the date parser)
    - Prefer <time datetime> when present; fall back to a narrow date-time text slice
    - Handle '@' separators commonly used by MT (“Aug 30 @ 6:30 pm - 8:30 pm”)
    """
    soup = BeautifulSoup(html, "html.parser")

    # Limit scope to the events list container if present.
    root = _first(
        soup,
        [
            ".tribe-events-calendar-list",  # v5
            "#tribe-events",
            ".tribe-common",  # generic shell
            "main",
        ],
    ) or soup

    # candidate event blocks across MT variants
    event_blocks = _all(
        root,
        [
            "article.tribe-events-calendar-list__event",   # v5
            "div.tribe-events-calendar-list__event",
            "li.type-tribe_events",
            "article.type-tribe_events",
            "div.type-tribe_events",
            "div.tribe-common-g-row",  # some list templates
        ],
    )

    items: List[Dict[str, Any]] = []
    for block in event_blocks:
        # Title + URL
        title, url = _extract_title_url(block, base_url)
        title = title.strip()
        if not title:
            continue  # skip nameless rows (usually ads/placeholders)

        # Date/time
        start_iso: Optional[str] = None
        end_iso: Optional[str] = None

        prefer = _prefer_times(block)
        if prefer:
            start_iso, end_iso = prefer
        else:
            dt_text = _extract_dt_text(block)
            # Normalize some noise; keep short
            # Guard against dumping entire page (heuristic: cap length)
            dt_text = " ".join(dt_text.split())[:300]
            # Replace bullets/dashes that often separate ranges
            dt_text = dt_text.replace("–", "-").replace("—", "-")
            # Now ask the existing helper to parse a range
            try:
                dt = parse_datetime_range(dt_text)
                start_iso = dt["start"].isoformat()
                if dt.get("end"):
                    end_iso = dt["end"].isoformat()
            except Exception:
                # could not confidently parse; skip this event
                continue

        # Location
        location = _extract_location(block)

        item: Dict[str, Any] = {
            "title": title,
            "start": start_iso,
            "location": location,
        }
        if end_iso:
            item["end"] = end_iso
        if url:
            item["url"] = url

        # sanity check: must have start
        if item.get("start"):
            items.append(item)

    return items
