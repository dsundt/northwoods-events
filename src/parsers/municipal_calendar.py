# -*- coding: utf-8 -*-
"""
Municipal calendar (WordPress / assorted) parser.

Fixes:
- Avoid treating "Google Calendar" (add-to-calendar links) as the event title.
- Prefer JSON-LD Event when available; otherwise take the visible event title text and ignore gCal export anchors.
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
    loc = obj.get("location")
    location = ""
    if isinstance(loc, dict):
        location = _clean(loc.get("name") or loc.get("address") or "")
    if not name or not start:
        return None
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

def parse(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    rows: List[Dict[str, Any]] = []

    # 1) JSON-LD
    for ev in _iter_jsonld_events(soup):
        rows.append(ev)
    if rows:
        return rows

    # 2) DOM fallback — attempt common WP calendar layouts
    # Try list items with a title link not pointing to google.com/calendar
    for li in soup.select("li, article, .event, .ai1ec-event"):
        # Candidate title link
        a = None
        for cand in li.select("a"):
            href = (cand.get("href") or "").strip()
            text = _clean(cand.get_text())
            if not text:
                continue
            if "google.com/calendar" in href.lower():
                # skip export links
                continue
            # Heuristic: prefer links that look like event detail pages (not anchors starting with "?")
            if href and not href.startswith("#"):
                a = cand
                break

        title = _clean(a.get_text()) if a else ""
        url = (a.get("href") if a else "") if a else ""

        # find time info if present
        time_tag = li.select_one("time[datetime]")
        iso_hint = (time_tag.get("datetime").strip() if time_tag else "")

        # look for human-readable date text too (sibling spans)
        dt_text = ""
        dt_el = li.select_one(".ai1ec-time, .event-date, .date, .time")
        if dt_el and not iso_hint:
            dt_text = _clean(dt_el.get_text())

        if title and title.lower() != "google calendar":
            rows.append({
                "title": title,
                "url": url,
                "location": _clean((li.select_one(".location, .venue, .place") or {}).get_text() if li else ""),
                "date_text": dt_text,
                "iso_hint": iso_hint,
                "iso_end_hint": "",
            })

    # Dedup
    seen = set()
    deduped = []
    for r in rows:
        key = (r["title"], r["url"], r["iso_hint"] or r["date_text"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped
