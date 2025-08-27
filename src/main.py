#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import pytz
import requests
from bs4 import BeautifulSoup

# ---- Configuration ---------------------------------------------------------

CENTRAL_TZ = pytz.timezone("America/Chicago")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_DIR = os.path.join(ROOT, "state")
SNAP_DIR = os.path.join(STATE_DIR, "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# ---- Helpers: IO, HTTP, logging -------------------------------------------

def _now_central() -> datetime:
    return datetime.now(tz=CENTRAL_TZ)

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_text(path: str, txt: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)

def fetch(url: str, *, expect_json: bool = False, timeout: int = 30) -> tuple[int, str]:
    headers = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    r = requests.get(url, headers=headers, timeout=timeout)
    ct = r.headers.get("Content-Type", "")
    if expect_json and "application/json" not in ct:
        # we’ll still return text; caller can decide what to do
        pass
    return r.status_code, r.text

def snapshot_html(name: str, html: str) -> None:
    safe = re.sub(r"\s+", "_", name.lower())
    path = os.path.join(SNAP_DIR, f"{safe}.html")
    write_text(path, html)

# ---- SAFE TEXT CLEANING (fix for the hyphen-in-class bug) -----------------
# The previous implementation had a character class with a mid-class hyphen,
# which causes "bad character range" errors on some pages when fed through re.
# Solution: put "-" at the END of the class (or escape it), and include en/em dashes.

BAD_CHARS_RE = re.compile(r"[^\w\s,.&/()#@:+–—-]")  # <- hyphen is LAST; also allow en/em dash

def clean_text(s: Optional[str]) -> str:
    """
    Normalize whitespace and remove only truly junk characters.
    Keeps hyphens/dashes by allowing '-', '–', '—'.
    """
    if not s:
        return ""
    # collapse whitespace
    s = re.sub(r"\s+", " ", s.strip())
    # strip zero-width, odd spaces
    s = s.replace("\u200b", "").replace("\ufeff", "")
    # remove junk but KEEP -, en dash, em dash
    s = BAD_CHARS_RE.sub("", s)
    return s.strip()

# ---- Normalization (delegates to src/normalize.py if present) --------------

# We try to import your normalize module (which you’ve been iterating on).
# If it’s not present for some reason, we’ll fall back to a minimal local shim.
try:
    from src.normalize import parse_datetime_range as _parse_datetime_range
    from src.normalize import clean_text as _normalize_clean_text  # if user prefers theirs
    HAVE_EXTERNAL_NORMALIZE = True
except Exception:
    HAVE_EXTERNAL_NORMALIZE = False

def parse_datetime_range(date_text: str,
                         iso_hint: Optional[str] = None,
                         iso_end_hint: Optional[str] = None,
                         tzname: Optional[str] = "America/Chicago") -> Tuple[datetime, datetime, bool]:
    if HAVE_EXTERNAL_NORMALIZE:
        # Use your improved implementation
        return _parse_datetime_range(date_text=date_text, iso_hint=iso_hint, iso_end_hint=iso_end_hint, tzname=tzname)
    # Fallback: very basic
    start = _now_central()
    end = start + timedelta(hours=2)
    return start, end, False

# If normalize.clean_text exists, you can opt to use it by uncommenting:
# def clean_text(s: Optional[str]) -> str:
#     return _normalize_clean_text(s) if HAVE_EXTERNAL_NORMALIZE else _local_clean_text(s)

# ---- Data structures -------------------------------------------------------

@dataclass
class EventRow:
    title: str
    start_iso: Optional[str]
    end_iso: Optional[str]
    date_text: str
    url: str
    location: str
    source: str

# ---- Parsers ---------------------------------------------------------------

def parse_modern_tribe_html(html: str, source_name: str) -> List[EventRow]:
    """
    Very forgiving HTML parser for Modern Tribe list/grid pages.
    We only need title, link, a date/time-ish snippet, & location if available.
    """
    soup = BeautifulSoup(html, "lxml")

    # Most themes: articles with class 'tribe_events' OR generic list items with obvious anchors
    # We’ll be lenient and collect candidates by anchors that link to single event pages.
    rows: List[EventRow] = []

    # Title links — try common selectors first
    for a in soup.select("a.tribe-event-url, a.url, h3 a, h2 a, .tribe-events-calendar-list__event-title-link"):
        href = a.get("href") or ""
        title = clean_text(a.get_text())
        if not title or not href:
            continue

        # Try to find a nearby date/time text
        date_node = None
        # Look in parents/siblings for time/date bits
        parent = a.find_parent()
        if parent:
            date_node = parent.select_one(
                ".tribe-event-date-start, .tribe-events-c-small-tiles__date, .tribe-event-date, time, .tribe-events-event-datetime"
            )
        date_text = clean_text(date_node.get_text()) if date_node else ""

        # Try location hints
        loc_node = None
        if parent:
            loc_node = parent.select_one(".tribe-events-venue, .tribe-venue, .tribe-events-venue__name, .tribe-address")
        location = clean_text(loc_node.get_text()) if loc_node else ""

        rows.append(EventRow(
            title=title,
            start_iso=None,
            end_iso=None,
            date_text=date_text,
            url=href,
            location=location,
            source=source_name
        ))
    return rows

def parse_growthzone_html(html: str, source_name: str) -> List[EventRow]:
    """
    GrowthZone calendar pages vary. Grab anchors inside calendar tiles.
    """
    soup = BeautifulSoup(html, "lxml")
    rows: List[EventRow] = []

    for card in soup.select("a[href*='/events/details/'], a[href*='/events/details/']:has(h3), .gz_event a"):
        href = card.get("href") or ""
        title = clean_text(card.get_text())
        if not title or not href:
            continue

        wrap = card.find_parent() or card
        date_text = ""
        dt = wrap.select_one("time, .date, .gz_event_date, .gz_eventTime, .gz_event_date_time")
        if dt:
            date_text = clean_text(dt.get_text())

        loc = ""
        lv = wrap.select_one(".gz_event_location, .location, .gz_address, .gz_addr")
        if lv:
            loc = clean_text(lv.get_text())

        rows.append(EventRow(
            title=title, start_iso=None, end_iso=None,
            date_text=date_text, url=href, location=loc, source=source_name
        ))
    return rows

def ingest_ics_text(ics_text: str, source_name: str) -> List[EventRow]:
    """
    Basic ICS ingestion that does not rely on strict parsing (block some sites serving HTML).
    If the text does not look like ICS, we return empty.
    """
    # quick sniff
    if not ics_text.lstrip().upper().startswith("BEGIN:VCALENDAR"):
        return []

    # minimal event extraction
    events: List[EventRow] = []
    # Split by VEVENT
    chunks = re.split(r"(?mi)^BEGIN:VEVENT\s*$", ics_text)
    for chunk in chunks[1:]:
        body = chunk.split("END:VEVENT", 1)[0]

        def get(field: str) -> str:
            m = re.search(rf"(?mi)^{field}:(.+)\s*$", body)
            return m.group(1).strip() if m else ""

        summary = clean_text(get("SUMMARY"))
        dtstart = get("DTSTART")
        dtend = get("DTEND")
        url = get("URL")
        loc = clean_text(get("LOCATION"))

        if not summary:
            continue
        events.append(EventRow(
            title=summary,
            start_iso=dtstart or None,
            end_iso=dtend or None,
            date_text="",  # not needed because we have ISO
            url=url,
            location=loc,
            source=source_name
        ))
    return events

# ---- Normalization of collected rows --------------------------------------

def normalize_rows(rows: List[EventRow], default_tz: str = "America/Chicago") -> List[dict]:
    normalized: List[dict] = []
    for r in rows:
        # Prefer ISO hints when present (usually for ICS cases)
        start_iso = r.start_iso
        end_iso = r.end_iso
        if start_iso or end_iso:
            start_dt, end_dt, all_day = parse_datetime_range("", start_iso, end_iso, tzname=default_tz)
        else:
            start_dt, end_dt, all_day = parse_datetime_range(r.date_text or "", None, None, tzname=default_tz)

        normalized.append({
            "title": r.title,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "all_day": all_day,
            "url": r.url,
            "location": r.location,
            "source": r.source,
        })
    return normalized

# ---- Sources ---------------------------------------------------------------

def load_sources(path: str) -> tuple[list[dict], dict]:
    if not os.path.isabs(path):
        # Try repo root, then src/
        candidate = os.path.join(ROOT, path)
        if os.path.exists(candidate):
            path = candidate
        else:
            alt = os.path.join(ROOT, "src", path)
            if os.path.exists(alt):
                path = alt
    with open(path, "r", encoding="utf-8") as f:
        import yaml
        doc = yaml.safe_load(f)
    return doc.get("sources", []), doc.get("defaults", {})

# ---- Driver ---------------------------------------------------------------

def process_source(src: dict) -> tuple[list[dict], dict]:
    """
    Returns (normalized_events, stats)
    """
    name = src["name"]
    kind = src.get("kind", "modern_tribe")
    url = src["url"]
    stats = {"name": name, "url": url, "fetched": 0, "parsed": 0, "added": 0}

    # fetch primary
    code, text = fetch(url)
    stats["fetched"] = 1
    snapshot_html(name, text)

    rows: List[EventRow] = []

    try:
        if kind == "modern_tribe":
            rows = parse_modern_tribe_html(text, name)
        elif kind == "growthzone":
            rows = parse_growthzone_html(text, name)
        elif kind == "ics":
            rows = ingest_ics_text(text, name)
        elif kind == "municipal":
            # treat like a simple calendar: generic link+date scraping
            rows = parse_modern_tribe_html(text, name)
        else:
            # fallback: try lenient modern tribe logic
            rows = parse_modern_tribe_html(text, name)
    except re.error as rex:
        # Catch regex crashes (this is where your error came from). We log and continue.
        stats["error"] = f"regex_error: {rex!r}"
        return [], stats

    stats["parsed"] = len(rows)

    # If HTML path yields nothing and an ICS fallback is defined, try it
    if not rows and src.get("ics_url"):
        ics_url = src["ics_url"]
        code2, txt2 = fetch(ics_url)
        snapshot_html(f"{name} (ICS) (ics_response)", txt2)
        more = ingest_ics_text(txt2, f"{name} (ICS)")
        rows.extend(more)
        stats["ics_name"] = f"{name} (ICS)"
        stats["ics_url"] = ics_url
        if not more and txt2:
            stats["ics_error"] = "ICS endpoint returned non-ICS (likely HTML/blocked)"

    normalized = normalize_rows(rows)
    stats["added"] = len(normalized)
    # optional small sample
    stats["samples"] = [{
        "title": e["title"],
        "start": e["start"],
        "location": e["location"],
        "url": e["url"],
    } for e in normalized[:3]]

    return normalized, stats

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="sources.yaml")
    ap.add_argument("--out", default=os.path.join(ROOT, "northwoods.ics"))
    ap.add_argument("--report", default=os.path.join(STATE_DIR, "last_run_report.json"))
    args = ap.parse_args()

    sources, defaults = load_sources(args.sources)

    all_events: List[dict] = []
    report_sources: List[dict] = []

    for src in sources:
        norm, stats = process_source(src)
        all_events.extend(norm)
        report_sources.append(stats)

    # Save run report (what you’ve been inspecting)
    write_text(args.report, json.dumps({
        "when": _now_central().isoformat(),
        "timezone": "America/Chicago",
        "sources": report_sources
    }, indent=2))

    # (Optional) write ICS output — omitted here to keep this file focused on parsing;
    # your existing ICS writer can stay as-is if it lives elsewhere.

if __name__ == "__main__":
    main()
