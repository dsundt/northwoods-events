from __future__ import annotations
import re
from datetime import date, datetime
from typing import Optional, Tuple

# Month dictionary
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

# Regex patterns
_M = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
_TIME = r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>am|pm)"
_DATE1 = re.compile(rf"(?P<mon>{_M})\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?", re.I)
_DATE_AND_TIME = re.compile(rf"{_DATE1.pattern}(?:\s*@\s*(?P<stime>{_TIME}))?", re.I)
_RANGE = re.compile(rf"(?P<m1>{_M})?\s*(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<m2>{_M})?\s*(?P<d2>\d{{1,2}})", re.I)
_TIME_ONLY = re.compile(_TIME, re.I)
_URL_MDY = re.compile(r"-(?P<mm>\d{2})-(?P<dd>\d{2})-(?P<yyyy>\d{4})(?:-|$)")

def _infer_year(mon: int, day: int, explicit: Optional[int]) -> int:
    if explicit:
        return explicit
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

def parse_date_string(raw: str) -> Optional[date]:
    if not raw:
        return None
    m = _DATE1.search(raw)
    if not m:
        # range like "Oct 4 - 5" → return the start date
        r = _RANGE.search(raw)
        if r:
            m1 = r.group("m1") or r.group("m2")
            if not m1:
                return None
            mon = MONTHS[m1.lower()]
            d1 = int(r.group("d1"))
            yr = _infer_year(mon, d1, None)
            return date(yr, mon, d1)
        return None
    mon = MONTHS[m.group("mon").lower()]
    d = int(m.group("day"))
    yr = _infer_year(mon, d, int(m.group("year")) if m.group("year") else None)
    return date(yr, mon, d)

def parse_time_string(raw: str) -> Optional[Tuple[int,int]]:
    if not raw:
        return None
    m = _TIME_ONLY.search(raw)
    if not m:
        return None
    h = int(m.group("h"))
    mm = int(m.group("m"))
    h, mm = _to_24(h, mm, m.group("ampm"))
    return h, mm

def parse_datetime_range(raw: str) -> str:
    """Return ISO start from a freeform string (month day [year] [@ time])."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError(f"Could not find a date in: {raw!r}")
    m = _DATE_AND_TIME.search(raw)
    if m:
        mon = MONTHS[m.group("mon").lower()]
        d = int(m.group("day"))
        yr = _infer_year(mon, d, int(m.group("year")) if m.group("year") else None)
        if m.group("stime"):
            h = int(m.group("h")); mm = int(m.group("m"))
            h, mm = _to_24(h, mm, m.group("ampm"))
            dt = datetime(yr, mon, d, h, mm)
        else:
            dt = datetime(yr, mon, d)
        return dt.isoformat()
    # range fallback
    d = parse_date_string(raw)
    if d:
        return datetime(d.year, d.month, d.day).isoformat()
    raise ValueError(f"Could not find a date in: {raw!r}")

def combine_date_and_time(date_iso_or_date: str, time_text: str) -> Optional[str]:
    """
    Only combines if date_iso_or_date looks like a real date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS...).
    Otherwise, returns None.
    """
    if not date_iso_or_date or not re.match(r"^\d{4}-\d{2}-\d{2}", date_iso_or_date):
        return None
    date_part = date_iso_or_date.split("T")[0]
    t = parse_time_string(time_text)
    try:
        dt = datetime.fromisoformat(f"{date_part}T00:00:00")
        if t:
            h, m = t
            dt = dt.replace(hour=h, minute=m)
        return dt.isoformat()
    except Exception:
        return None

def parse_date_from_url(url: str) -> Optional[str]:
    """Extract YYYY-MM-DD from GrowthZone detail URLs like '-08-01-2025-12345'."""
    m = _URL_MDY.search(url or "")
    if not m:
        return None
    yyyy = int(m.group("yyyy")); mm = int(m.group("mm")); dd = int(m.group("dd"))
    return datetime(yyyy, mm, dd).isoformat()
