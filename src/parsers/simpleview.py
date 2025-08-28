from __future__ import annotations

from typing import List, Dict, Any, Iterable, Tuple, Set
from datetime import datetime
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from dateutil import parser as dtp

from parsers._text import text as _text
from utils.dates import parse_datetime_range  # (start, end|None)

MONTH_PAT = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(,\s*\d{4})?",
    re.IGNORECASE,
)

def _iso(dt: datetime) -> str:
    return dt.isoformat()

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _add(items: List[Dict[str, Any]], seen: Set[Tuple[str, str, str]], node: Dict[str, Any]) -> None:
    key = (node.get("title", ""), node.get("start", ""), node.get("url", ""))
    if all(key) and key not in seen:
        items.append(node)
        seen.add(key)

def _parse_jsonld(soup: BeautifulSoup, base_url: str) -> Iterable[Dict[str, Any]]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = script.string or script.get_text("", strip=True)
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue

        nodes = []
        if isinstance(data, list):
            nodes = data
        elif isinstance(data, dict):
            nodes = data.get("@graph") or [data]

        for n in nodes:
            try:
                t = (n.get("@type") or n.get("type") or "")
                if isinstance(t, list):
                    is_event = any(str(x).lower() == "event" for x in t)
                else:
                    is_event = str(t).lower() == "event"
                if not is_event:
                    continue

                title = _clean(n.get("name") or "")
                start_raw = n.get("startDate") or n.get("startTime") or ""
                end_raw = n.get("endDate") or n.get("endTime") or ""
                url = urljoin(base_url, n.get("url") or "")
                loc = ""
                location = n.get("location")
                if isinstance(location, dict):
                    loc = _clean(location.get("name") or location.get("address", "") or "")
                elif isinstance(location, str):
                    loc = _clean(location)

                if not (title and start_raw and url):
                    continue

                start_dt = dtp.parse(start_raw)
                end_dt = None
                if end_raw:
                    try:
                        end_dt = dtp.parse(end_raw)
                    except Exception:
                        end_dt = None

                node: Dict[str, Any] = {
                    "title": title,
                    "start": _iso(start_dt),
                    "url": url,
                }
                if end_dt:
                    node["end"] = _iso(end_dt)
                if loc:
                    node["location"] = loc
                yield node
            except Exception:
                continue

def _date_from_card(card: Tag) -> Tuple[Optional[datetime], Optional[datetime]]:
    # Common Simpleview listing bits: classes like event-date, event-card__date, listing_date
    for cls in [
        "event-date", "event_date", "event-card__date", "listing_date", "date", "event-listing__date"
    ]:
        n = card.find(class_=re.compile(rf"\b{cls}\b", re.I))
        if n:
            date_txt = _clean(_text(n))
            if date_txt:
                # ranges like "Sep 4, 2025 - Sep 6, 2025" or single dates
                try:
                    s, e = parse_datetime_range(date_txt)
                    return s, e
                except Exception:
                    try:
                        s = dtp.parse(date_txt, fuzzy=True)
                        return s, None
                    except Exception:
                        pass

    # scan nearby text for month names
    s = _text(card)
    m = MONTH_PAT.search(s)
    if m:
        try:
            d = dtp.parse(m.group(0), fuzzy=True)
            return d, None
        except Exception:
            pass
    return None, None

def _parse_dom(soup: BeautifulSoup, base_url: str) -> Iterable[Dict[str, Any]]:
    """
    Minocqua & Oneida often use Simpleview list cards:
      - anchor to '/event/' or '/events/' with title
      - date in sibling span/div
    """
    # Try a narrow selector first for performance
    cards = []
    # Common containers
    for sel in [
        ("div", {"class": re.compile(r"(event\-card|event\-listing|listing)", re.I)}),
        ("li", {"class": re.compile(r"(event|listing)", re.I)}),
        ("article", {"class": re.compile(r"(event|listing)", re.I)}),
        # final fallback: scan anchors directly
    ]:
        cards.extend(soup.find_all(*sel))

    yielded: Set[str] = set()

    def emit_from_anchor(a: Tag, container: Tag) -> Optional[Dict[str, Any]]:
        href = a.get("href") or ""
        if not re.search(r"/event[s]?/", href, re.I):
            return None
        title = _clean(_text(a))
        if not title:
            # Some themes put title in a heading inside anchor
            h = a.find(["h2", "h3", "h4"])
            title = _clean(_text(h)) if h else ""
        if not title:
            return None

        url = urljoin(base_url, href)
        if url in yielded:
            return None

        start_dt, end_dt = _date_from_card(container or a)
        if not start_dt:
            # look one level up or down for a date block
            parent = container.parent if container else None
            if parent:
                start_dt, end_dt = _date_from_card(parent)
        if not start_dt:
            return None

        loc = ""
        for cls in ["event-location", "location", "event-card__location", "listing_location"]:
            n = (container or a).find(class_=re.compile(rf"\b{cls}\b", re.I))
            if n:
                loc = _clean(_text(n))
                break

        node: Dict[str, Any] = {
            "title": title,
            "start": _iso(start_dt),
            "url": url,
        }
        if end_dt:
            node["end"] = _iso(end_dt)
        if loc:
            node["location"] = loc

        yielded.add(url)
        return node

    # Pass 1: cards
    for card in cards:
        for a in card.find_all("a", href=True):
            node = emit_from_anchor(a, card)
            if node:
                yield node

    # Pass 2: raw anchors (fallback if no card structure matched)
    if not yielded:
        for a in soup.find_all("a", href=True):
            node = emit_from_anchor(a, a.parent or a)
            if node:
                yield node

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Parse Simpleview list pages (e.g., Minocqua & Oneida).
    Strategy:
      1) JSON-LD Event nodes (rare on list pages but cheap to check)
      2) DOM list cards with '/event/' anchors + date siblings
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, str]] = set()

    for node in _parse_jsonld(soup, base_url):
        _add(items, seen, node)
    for node in _parse_dom(soup, base_url):
        _add(items, seen, node)

    return items
