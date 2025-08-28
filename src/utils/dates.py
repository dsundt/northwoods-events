# src/utils/dates.py
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Tuple
import re

from dateutil import parser as dtp

# separators like "10:00 AM – 1:00 PM", "to", "through", "thru"
_RANGE_SEP = re.compile(r"\s*(?:–|—|-|to|through|thru)\s*", re.IGNORECASE)

def _parse_one(piece: str, default: datetime | None = None) -> datetime:
    """
    Parse a datetime (ISO or free text). If 'piece' contains only a time,
    'default' supplies the date.
    """
    if default is not None:
        return dtp.parse(piece, default=default, fuzzy=True)
    return dtp.parse(piece, fuzzy=True)

def parse_datetime_range(text: str) -> Tuple[datetime, datetime]:
    """
    Accepts strings like:
      "2025-09-12T10:00-05:00 – 2025-09-12T12:00-05:00"
      "Fri Sep 12, 10:00 AM – 12:00 PM"
      "Sep 12, 10 AM to Sep 13, 1 PM"
      "Sep 12, 2025"        # all-day or single instant -> end == start
    Always returns exactly (start, end).
    """
    raw = (text or "").strip()
    if not raw:
        now = datetime.now()
        return now, now

    parts = [p for p in _RANGE_SEP.split(raw) if p.strip()]
    if len(parts) == 1:
        start = _parse_one(parts[0])
        end = start
        return start, end

    # Use first part to establish a full datetime baseline
    start = _parse_one(parts[0])
    # Parse the right side; if it omits a date, inherit from 'start'
    end = _parse_one(parts[1], default=start)

    # If end < start and the right side looked like a time-only, roll to next day
    if end < start and parts[1] and not re.search(r"\d{4}|\bjan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec", parts[1], re.I):
        end = end + timedelta(days=1)

    return start, end
