# -*- coding: utf-8 -*-
"""
GrowthZone parser.

Note: Many GrowthZone calendars are JS-rendered. This parser:
- Tries JSON-LD first (if the site emits schema on the page).
- Then falls back to server-rendered anchors that look like event details: /events/details/ or /events/<slug>
- Skips nav/placeholder links.
"""

from __future__ import annotations
import json, re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _coerce_event(obj: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    t = obj.get("@type")
    if isinstance(t, list):
        is_event = any(tt.lower() == "event" for tt in map(str, t))
    else:
        is_event = (str(t).lower() == "event")
    if not is_event:
        return None
    name = _clean(obj.get("name") or "")
    url = _clean(obj.get("url") or "")
    start = _clean(obj.get("startDate") or "")
    end = _clean(obj.get("endDate") or "")
    if not name or not start:
        return None
    location = ""
    loc = obj.get("location")
    if isinstance(loc, dict):
        location = _clean(loc.get("name") or loc.get("address") or "")
    return {
        "title": name,
        "url": url,
        "location": location,
        "date_text": "",
        "iso_hint": start,
        "iso_end_hint": end or "",
    }

def _iter_jsonld_events(soup: BeautifulSoup):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = (tag.string or tag.get_text() or "").strip()
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue
        if isinstance(data, dict) and "@graph" in data and isinstance(data["@graph"], list):
            for it in data["@graph"]:
                ev = _coerce_event(it)
                if ev:
                    yield ev
        elif isinstance(data, list):
            for it in data:
                ev = _coerce_event(it)
                if ev:
                    yield ev
        elif isinstance(data, dict):
            ev = _coerce_event(data)
            if ev:
                yield ev

DETAIL_RE = re.compile(r"/events?/(details|[^/]+)", re.I)

def parse(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    rows: List[Dict[str, Any]] = []

    # 1) JSON-LD first
    for ev in _iter_jsonld_events(soup):
        rows.append(ev)
    if rows:
        return rows

    # 2) Server-side anchors that look like event detail pages
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if not DETAIL_RE.search(href):
            continue
        title = _clean(a.get_text())
        if not title or len(title) < 3:
            continue
        # pick up time near link if present
        container = a.find_parent(["article", "li", "div"]) or soup
        time_tag = container.select_one("time[datetime]")
        iso = (time_tag.get("datetime").strip() if time_tag else "")
        rows.append({
            "title": title,
            "url": href,
            "location": "",
            "date_text": "",
            "iso_hint": iso,
            "iso_end_hint": "",
        })

    # Dedup
    seen = set()
    deduped = []
    for r in rows:
        key = (r["title"], r["url"], r["iso_hint"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped
