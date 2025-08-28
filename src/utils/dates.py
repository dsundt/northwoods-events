# src/utils/dates.py
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple
from dateutil import parser as dtp

# Split tokens like "10:00 AM – 1:00 PM", "to", "through", "thru"
_RANGE_SEP = re.compile(r"\s*(?:–|—|-|to|through|thru)\s*", re.IGNORECASE)

# Heuristics to decide if free text even looks like a date/time
_HAS_DATE_HINT = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b|\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2}",
    re.IGNORECASE,
)

def parse_iso_or_text(piece: str, *, default: datetime | None = None) -> datetime:
    """Parse ISO-8601 or human text; if only a time is present, 'default' supplies the date."""
    if default is not None:
        return dtp.parse(piece, default=default, fuzzy=True)
    return dtp.parse(piece, fuzzy=True)

def try_parse_datetime_range(text: str) -> Optional[Tuple[datetime, datetime]]:
    """
    Best-effort parser. Returns (start, end) or None if no plausible date is found.
    Never raises.
    """
    raw = (text or "").strip()
    # Quick rejections: too short or no date-ish tokens
    if len(raw) < 6:
        return None
    if not _HAS_DATE_HINT.search(raw):
        return None

    parts = [p for p in _RANGE_SEP.split(raw) if p.strip()]
    try:
        if len(parts) == 1:
            start = parse_iso_or_text(parts[0])
            return start, start

        start = parse_iso_or_text(parts[0])
        end = parse_iso_or_text(parts[1], default=start)

        # If end < start and right side looked like time-only, roll to next day
        if end < start and not _HAS_DATE_HINT.search(parts[1]):
            end = end + timedelta(days=1)
        return start, end
    except Exception:
        return None
