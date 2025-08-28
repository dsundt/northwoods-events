from __future__ import annotations

import re
from datetime import datetime, date
from typing import Tuple

__all__ = ["parse_datetime_range"]

# Month map
MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Patterns:
# "Aug 31, 2025 10:00 am"
# "August 30 @ 6:30 pm - 8:30 pm"
# "Oct 4 - Oct 5" / "October 4 - 5"
_M = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
_TIME = r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>am|pm)"
_DATE1 = re.compile(rf"(?P<mon>{_M})\s+(?P<day>\d{{1,2}})(?:,?\s*(?P<year>\d{{4}}))?(?:\s*(?:@|,)?\s*(?P<stime>{_TIME}))?", re.I)
_RANGE = re.compile(rf"(?P<m1>{_M})?\s*(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<m2>{_M})?\s*(?P<d2>\d{{1,2}})", re.I)


def _infer_year(mon: int, day: int, year: int | None) -> int:
    if year:
        return year
    today = date.today()
    candidate = date(today.year, mon, day)
    if (candidate - today).days < -300:
        return today.year + 1
    return today.year


def _to_24(h: int, m: int, ampm: str) -> Tuple[int, int]:
    ampm = ampm.lower()
    h = h % 12
    if ampm == "pm":
        h += 12
    return h, m


def parse_datetime_range(raw: str) -> str:
    """
    Extracts and returns the *start* of a date/time range as ISO 8601 str.
    Raises ValueError if nothing usable is found.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError(f"Could not find a date in: {raw!r}")

    # Case 1: single date with optional time
    m = _DATE1.search(raw)
    if m:
        mon = MONTHS[m.group("mon").lower()]
        day = int(m.group("day"))
        year = int(m.group("year")) if m.group("year") else None
        year = _infer_year(mon, day, year)
        if m.group("stime"):
            h = int(m.group("h"))
            mm = int(m.group("m"))
            ampm = m.group("ampm")
            h, mm = _to_24(h, mm, ampm)
            dt = datetime(year, mon, day, h, mm)
        else:
            dt = datetime(year, mon, day)
        return dt.isoformat()

    # Case 2: date range like "Oct 4 - Oct 5" or "October 4 - 5"
    r = _RANGE.search(raw)
    if r:
        m1 = r.group("m1") or r.group("m2")
        if not m1:
            raise ValueError(f"Could not find a date in: {raw!r}")
        mon = MONTHS[m1.lower()]
        day = int(r.group("d1"))
        year = _infer_year(mon, day, None)
        dt = datetime(year, mon, day)
        return dt.isoformat()

    raise ValueError(f"Could not find a date in: {raw!r}")
