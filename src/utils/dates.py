# src/utils/dates.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

try:
    # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

# -- Public API ---------------------------------------------------------------

__all__ = ["parse_datetime_range"]

# -- Helpers ------------------------------------------------------------------

_MONTHS = {
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

_TIME_RE = re.compile(
    r"\b(?P<h>\d{1,2})(:(?P<m>\d{2}))?\s*(?P<ampm>[APap][Mm])?\b"
)

# Month-name date like "Jul 4, 2025" or "July 4, 2025"
_MNAME_DATE_RE = re.compile(
    r"\b(?P<mon>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?\s*,\s*(?P<year>\d{4})\b"
)

# Numeric date like "7/4/2025" or "07/04/25"
_NUM_DATE_RE = re.compile(
    r"\b(?P<mon>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{2,4})\b"
)

@dataclass
class ParsedDate:
    year: int
    month: int
    day: int

def _coerce_tz(dt: datetime, tzname: Optional[str]) -> datetime:
    if tzname and ZoneInfo is not None:
        tz = ZoneInfo(tzname)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    return dt

def _parse_date(text: str) -> Optional[ParsedDate]:
    m = _MNAME_DATE_RE.search(text)
    if m:
        mon_name = m.group("mon").lower()
        mon = _MONTHS.get(mon_name[:3], _MONTHS.get(mon_name))
        if mon is None:
            return None
        return ParsedDate(int(m.group("year")), mon, int(m.group("day")))

    m = _NUM_DATE_RE.search(text)
    if m:
        year = int(m.group("year"))
        if year < 100:  # two-digit year -> 2000-2099
            year += 2000
        return ParsedDate(year, int(m.group("mon")), int(m.group("day")))

    return None

def _parse_time(text: str) -> Optional[tuple[int, int]]:
    m = _TIME_RE.search(text)
    if not m:
        return None
    h = int(m.group("h"))
    mnt = int(m.group("m") or 0)
    ampm = m.group("ampm")
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and h != 12:
            h += 12
        if ampm == "am" and h == 12:
            h = 0
    return h, mnt

def _build_dt(pd: ParsedDate, hm: Optional[tuple[int, int]]) -> datetime:
    if hm is None:
        return datetime(pd.year, pd.month, pd.day, 0, 0, 0)
    h, m = hm
    return datetime(pd.year, pd.month, pd.day, h, m, 0)

def _split_range(raw: str) -> tuple[str, Optional[str]]:
    # split on the first " - " (en dash and em dash variants too)
    parts = re.split(r"\s[-–—]\s", raw, maxsplit=1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]

# -- Main function ------------------------------------------------------------

def parse_datetime_range(raw: str, tzname: str = "America/Chicago") -> Tuple[datetime, Optional[datetime]]:
    """
    Parse a GrowthZone-like datetime range string into (start_dt, end_dt).

    Accepts examples such as:
      "Jul 4, 2025 5:00 PM - 8:00 PM"
      "July 4, 2025"
      "07/04/2025 9:00 AM - 12:00 PM"
      "Jul 4, 2025 9 AM - Jul 4, 2025 12 PM"
      "Tue Jul 2, 2025 5:00 PM - 8:30 PM"

    Returns timezone-aware datetimes if `zoneinfo` is available; otherwise naïve.
    If no end component is present, end_dt is None.
    """
    text = " ".join(raw.split())  # normalize spaces

    left, right = _split_range(text)

    # Parse left side (must contain a date; often includes a time)
    left_date = _parse_date(left)
    if not left_date:
        # Sometimes weekday prefixes exist; try stripping leading word
        left_date = _parse_date(re.sub(r"^[A-Za-z]{3,9}\s+", "", left))
    if not left_date:
        raise ValueError(f"Could not find a date in: {raw!r}")

    left_time = _parse_time(left)
    start_dt = _build_dt(left_date, left_time)
    start_dt = _coerce_tz(start_dt, tzname)

    # Parse right side (may be time-only, or full date+time, or None)
    if not right:
        return start_dt, None

    right_date = _parse_date(right)
    # If right date missing, inherit date from left
    if not right_date:
        right_date = left_date

    right_time = _parse_time(right)

    # If right side had neither date nor time, treat as no end
    if right_date is left_date and right_time is None and _parse_date(right) is None:
        return start_dt, None

    end_dt = _build_dt(right_date, right_time)
    end_dt = _coerce_tz(end_dt, tzname)

    # If no time on either side, make end None (all-day single date)
    if left_time is None and right_time is None:
        return start_dt, None

    # If parsed end earlier than start on same date (rare with AM/PM), bump a day
    if end_dt <= start_dt and (
        (right is not None) and (_parse_date(right) is None or right_date == left_date)
    ):
        try:
            from datetime import timedelta
            end_dt = end_dt + timedelta(days=1)
        except Exception:
            pass

    return start_dt, end_dt
