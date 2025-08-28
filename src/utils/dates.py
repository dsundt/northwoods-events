from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from dateutil import parser as dtp

# Month names to quickly screen strings that plausibly contain a date
_MONTH_RE = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|August|September|October|November|December)"
# Anything that looks like a month name, a 4-digit year, or a time-of-day
_DATEISH = re.compile(rf"{_MONTH_RE}|\b\d{{4}}\b|\b\d{{1,2}}:\d{{2}}\b", re.I)

def clean(s: str) -> str:
    return " ".join((s or "").split())

def looks_like_datetime(s: str) -> bool:
    """Fast, cheap check before attempting full parsing."""
    return bool(_DATEISH.search(s or ""))

def _parse_one(piece: str, tz: Optional[timezone] = None) -> datetime:
    dt = dtp.parse(clean(piece), fuzzy=True)
    if dt.tzinfo is None:
        # Default to local time if desired; most sites are Central
        dt = dt.replace(tzinfo=timezone(timedelta(hours=-5)))  # America/Chicago CDT
    return dt

def try_parse_datetime_range(raw: str, tz: Optional[timezone] = None) -> Optional[Tuple[datetime, Optional[datetime]]]:
    """
    Best-effort parse of a date/time range string.
    Returns (start, end?) or None if nothing date-like could be found.
    Never raises.
    """
    s = clean(raw)
    if not looks_like_datetime(s):
        return None

    # Common separators seen across sources
    seps = ["–", "—", "-", " to ", "– ", " — ", " / ", "|", "@", " from ", " until "]
    parts = None
    for sep in seps:
        if sep in s:
            parts = [p.strip(" ,•") for p in s.split(sep, 1)]
            break

    try:
        if not parts:
            start = _parse_one(s, tz)
            return (start, None)
        start = _parse_one(parts[0], tz)
        # If RHS doesn't parse, keep it as an all-day/single time
        try:
            end = _parse_one(parts[1], tz)
        except Exception:
            end = None
        return (start, end)
    except Exception:
        return None

def parse_datetime_range(raw: str, tz: Optional[timezone] = None) -> Tuple[datetime, Optional[datetime]]:
    """
    Strict version used by some callers. Raises ValueError when no date.
    """
    result = try_parse_datetime_range(raw, tz)
    if result is None:
        raise ValueError(f"Could not find a date in: {clean(raw)!r}")
    return result

def parse_iso_or_text(raw: str, tz: Optional[timezone] = None) -> datetime:
    """Convenience: single datetime parse that tolerates text noise."""
    res = try_parse_datetime_range(raw, tz)
    if res:
        return res[0]
    return _parse_one(raw, tz)
