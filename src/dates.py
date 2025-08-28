# src/utils/dates.py
from __future__ import annotations
import re
from datetime import datetime
from dateutil import parser as dtp
from typing import Tuple

ISO_SPLIT = re.compile(r"\s*(?:–|-|—|to|through|thru)\s*", re.IGNORECASE)

def parse_iso_or_text(dt_text: str) -> datetime:
    # Handles ISO-8601 and “Sept 5, 2025 7:00 pm” style text
    return dtp.parse(dt_text, fuzzy=True)

def parse_datetime_range(text: str) -> Tuple[datetime, datetime]:
    """
    Accepts strings like:
      '2025-09-12T10:00:00-05:00 – 2025-09-12T12:00:00-05:00'
      'Fri Sep 12, 10:00 AM – 12:00 PM'
      'Sep 12, 10 AM to Sep 13, 1 PM'
    Always returns exactly (start, end).
    """
    parts = ISO_SPLIT.split(text.strip())
    if len(parts) == 1:
        start = parse_iso_or_text(parts[0])
        # default 1 hour if no explicit end
        end = start.replace()  # shallow copy
        end = end + (end - end.replace(hour=end.hour))  # no-op to keep type
        end = start  # then set fallback end = start (all-day or instant)
        return start, end
    elif len(parts) >= 2:
        left, right = parts[0], parts[1]
        start = parse_iso_or_text(left)
        # If right omits the date, inherit date from left
        try:
            end = dtp.parse(right, default=start, fuzzy=True)
        except Exception:
            end = start
        if end < start:
            # handle overnight ranges where only time is specified
            end = end.replace(day=end.day + 1)
        return start, end
