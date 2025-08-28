from __future__ import annotations
import re
from datetime import datetime, date
from typing import Optional, Tuple

# Month table
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

# Robust, *anchored* month token — prevents matching "Mar" inside "Market"
_M = r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b"
_TIME = r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>am|pm)"
# Month day [, year] [@ time]
DATE_PRIMARY = re.compile(rf"(?P<mon>{_M})\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?(?:\s*@\s*(?P<time>{_TIME}))?", re.I)
# Day range where we only need the START: "Oct 4 - 5" or "Oct 4 - Oct 5"
DATE_RANGE = re.compile(rf"(?P<m1>{_M})?\s*(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<m2>{_M})?\s*(?P<d2>\d{{1,2}})", re.I)
# Time elsewhere in text – we join with the date match if present
TIME_ANYWHERE = re.compile(_TIME, re.I)

def _infer_year(month: int, day: int, explicit_year: Optional[int]) -> int:
    if explicit_year:
        return explicit_year
    today = date.today()
    candidate = date(today.year, month, day)
    # If it's ~next season (way in the past), roll forward
    if (candidate - today).days < -300:
        return today.year + 1
    return today.year

def _to_24(h: int, m: int, ampm: str) -> Tuple[int, int]:
    h = h % 12
    if ampm.lower() == "pm":
        h += 12
    return h, m

def parse_datetime_range(raw: str) -> str:
    """
    Return an ISO8601 local-naive start datetime string parsed from messy event text like:
      - "August 30 @ 6:30 pm - 8:30 pm"
      - "Oct 4 - Oct 5"
      - "Aug 31, 2025 10:00 am"
      - "Featured 10:00 am Labor Day Arts and Crafts Show October 4"
    Raises ValueError if no usable date found.
    """
    txt = (raw or "").strip()
    if not txt:
        raise ValueError(f"Could not find a date in: {raw!r}")

    # 1) Primary: month day [, year] [@ time]
    m = DATE_PRIMARY.search(txt)
    if m:
        mon_name = m.group("mon")
        mon = MONTHS[mon_name.lower()]
        day = int(m.group("day"))
        year = _infer_year(mon, day, int(m.group("year")) if m.group("year") else None)
        if m.group("time"):
            hh = int(m.group("h")); mm = int(m.group("m")); ampm = m.group("ampm")
            hh, mm = _to_24(hh, mm, ampm)
            return datetime(year, mon, day, hh, mm).isoformat()
        # If there's a time elsewhere in the same string, borrow it
        t = TIME_ANYWHERE.search(txt)
        if t:
            hh = int(t.group("h")); mm = int(t.group("m")); ampm = t.group("ampm")
            hh, mm = _to_24(hh, mm, ampm)
            return datetime(year, mon, day, hh, mm).isoformat()
        return datetime(year, mon, day).isoformat()

    # 2) Ranges: we return the start of the range
    r = DATE_RANGE.search(txt)
    if r:
        m1 = r.group("m1") or r.group("m2")
        if not m1:
            raise ValueError(f"Could not find a date in: {raw!r}")
        mon = MONTHS[m1.lower()]
        day = int(r.group("d1"))
        year = _infer_year(mon, day, None)
        # Optional time anywhere
        t = TIME_ANYWHERE.search(txt)
        if t:
            hh = int(t.group("h")); mm = int(t.group("m")); ampm = t.group("ampm")
            hh, mm = _to_24(hh, mm, ampm)
            return datetime(year, mon, day, hh, mm).isoformat()
        return datetime(year, mon, day).isoformat()

    # 3) As a last chance, accept plain month+day with the time found elsewhere.
    m2 = re.search(rf"(?P<mon>{_M})\s+(?P<day>\d{{1,2}})\b", txt, re.I)
    if m2:
        mon = MONTHS[m2.group("mon").lower()]
        day = int(m2.group("day"))
        year = _infer_year(mon, day, None)
        t = TIME_ANYWHERE.search(txt)
        if t:
            hh = int(t.group("h")); mm = int(t.group("m")); ampm = t.group("ampm")
            hh, mm = _to_24(hh, mm, ampm)
            return datetime(year, mon, day, hh, mm).isoformat()
        return datetime(year, mon, day).isoformat()

    raise ValueError(f"Could not find a date in: {raw!r}")
