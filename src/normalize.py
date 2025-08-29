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

def parse_dt(text: str, tzname: Optional[str]) -> datetime:
    """Parse an ISO-ish or human datetime string and return aware local time."""
    tz = _safe_timezone(tzname)
    t = clean_text(text)
    # Handle simple date only -> midnight local
    try:
        dt = duparser.parse(t, fuzzy=True)
        if dt.tzinfo is None:
            dt = tz.localize(dt)
        else:
            dt = dt.astimezone(tz)
        return dt
    except Exception:
        # last resort: today at midnight
        today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        return today

def parse_datetime_range(text: str, tzname: Optional[str], default_minutes: int = 120) -> Tuple[datetime, datetime, bool]:
    """Very forgiving text range parser; returns (start, end, all_day)."""
    tz = _safe_timezone(tzname)
    s = clean_text(text)

    # ISO-like ranges first
    iso_times = re.findall(r"\d{4}-\d{2}-\d{2}[^,\sT]*T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?", s)
    if len(iso_times) >= 1:
        start = parse_dt(iso_times[0], tzname)
        end = start + timedelta(minutes=default_minutes)
        if len(iso_times) >= 2:
            end = parse_dt(iso_times[1], tzname)
            if end <= start:
                end = start + timedelta(minutes=default_minutes)
        return start, end, False

    # Fallback: one datetime in the string
    try:
        start = duparser.parse(s, fuzzy=True)
        start = _to_local(start, tz)
        end = start + timedelta(minutes=default_minutes)
        return start, end, False
    except Exception:
        now = datetime.now(tz)
        return now, now + timedelta(minutes=default_minutes), False

def _sid_for(title: str, start_iso: str, url: str, where: str) -> str:
    base = f"{clean_text(title)}|{start_iso}|{clean_text(url)}|{clean_text(where)}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()

def normalize_event(
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
    if start is None:
        # cannot proceed without start; try to set to now
        start = datetime.now(tz)
    if end is None or end <= start:
        end = start + timedelta(minutes=120)

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
