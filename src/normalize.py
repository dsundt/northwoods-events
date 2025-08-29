# src/normalize.py
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pytz
from dateutil import parser as duparser

CENTRAL_TZNAME = "America/Chicago"

def _safe_timezone(tzname: Optional[str]) -> pytz.BaseTzInfo:
    try:
        return pytz.timezone(tzname or CENTRAL_TZNAME)
    except Exception:
        return pytz.timezone(CENTRAL_TZNAME)

def _to_local(dt: datetime, tz: pytz.BaseTzInfo) -> datetime:
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt.astimezone(tz)

def clean_text(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def parse_dt(text: str, tzname: Optional[str]) -> Optional[datetime]:
    """Parse a datetime-ish string into a timezone-aware local datetime.
       Returns None if we cannot parse a plausible datetime."""
    t = clean_text(text)
    if not t:
        return None
    tz = _safe_timezone(tzname)
    try:
        dt = duparser.parse(t, fuzzy=True)
    except Exception:
        return None
    try:
        return _to_local(dt, tz)
    except Exception:
        return None

def parse_datetime_range(
    text: str,
    tzname: Optional[str],
    default_minutes: int = 120
) -> Tuple[Optional[datetime], Optional[datetime], bool]:
    """Forgiving range parser; returns (start, end, all_day). All may be None if unparseable."""
    s = clean_text(text)
    tz = _safe_timezone(tzname)

    # Detect 'all day' hints
    all_day = bool(re.search(r"\ball[- ]?day\b", s, flags=re.I))

    # Try ISO-like ranges embedded in text
    iso_times = re.findall(
        r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?",
        s
    )
    if iso_times:
        start = parse_dt(iso_times[0], tzname)
        end = parse_dt(iso_times[1], tzname) if len(iso_times) > 1 else None
        if start and end and end <= start:
            end = start + timedelta(minutes=default_minutes)
        if start and not end:
            end = start + (timedelta(days=1) if all_day else timedelta(minutes=default_minutes))
        return start, end, all_day

    # One timestamp case
    one = parse_dt(s, tzname)
    if one:
        end = one + (timedelta(days=1) if all_day else timedelta(minutes=default_minutes))
        return one, end, all_day

    # Give up
    return None, None, all_day

def _sid_for(title: str, start_iso: str, url: str, location: str) -> str:
    base = f"{title}|{start_iso}|{url}|{location}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]

def normalize_event(
    *,
    title: str,
    url: Optional[str],
    where: Optional[str],
    start: Optional[datetime],
    end: Optional[datetime],
    tzname: Optional[str],
    description: Optional[str] = None,
    all_day: bool = False,
    source_name: Optional[str] = None,
) -> Optional[dict]:
    """Return a normalized event dict for persistence + ICS."""
    title = clean_text(title)
    if not title:
        return None

    tz = _safe_timezone(tzname)

    # Strict: if start isn't parseable, drop the event
    if start is None:
        return None

    # Ensure end is sane
    if end is None or (end and end <= start):
        end = start + (timedelta(days=1) if all_day else timedelta(minutes=120))

    start_iso = _to_local(start, tz).isoformat()
    end_iso = _to_local(end, tz).isoformat()

    ev = {
        "title": title,
        "description": clean_text(description),
        "location": clean_text(where),
        "url": clean_text(url),
        "start_iso": start_iso,
        "end_iso": end_iso,
        "all_day": bool(all_day),
        "source": clean_text(source_name),
    }
    ev["sid"] = _sid_for(ev["title"], ev["start_iso"], ev["url"], ev["location"])
    return ev
