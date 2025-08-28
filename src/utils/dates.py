from __future__ import annotations
import re
from datetime import datetime, date
from typing import Optional, Tuple

# Month map (full tokens to avoid "Mar" in "Market")
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

# strict month token (not a prefix in longer words)
M_TOKEN = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"

TIME = r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>am|pm)"
DATE_SINGLE = re.compile(
    rf"(?P<mon>\b{M_TOKEN}\b)\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?(?:\s*@\s*(?P<stime>{TIME}))?",
    re.I,
)

# Ranges like "October 4 - October 5" or "Oct 4 - 5"
DATE_RANGE = re.compile(
    rf"(?P<m1>\b{M_TOKEN}\b)?\s*(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<m2>\b{M_TOKEN}\b)?\s*(?P<d2>\d{{1,2}})",
    re.I,
)

# Times sometimes appear first: "10:00 am - 4:00 pm • October 4"
TIME_THEN_DATE = re.compile(rf"^{TIME}.*?(?P<mon>{M_TOKEN})\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?", re.I)

def _infer_year(month: int, day: int, explicit: Optional[int]) -> int:
    if explicit:
        return explicit
    today = date.today()
    cand = date(today.year, month, day)
    if (cand - today).days < -300:
        return today.year + 1
    return today.year

def _to_24(h: int, m: int, ampm: str) -> Tuple[int, int]:
    h = h % 12
    if ampm.lower() == "pm":
        h += 12
    return h, m

def parse_iso_date(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> str:
    return datetime(y, m, d, hh, mm).isoformat()

def parse_datetime_range(raw: str) -> str:
    """Return ISO start datetime for common event strings; raises ValueError if none."""
    s = (raw or "").strip()
    if not s:
        raise ValueError(f"Could not find a date in: {raw!r}")

    # 1) "Aug 31, 2025 10:00 am" or "August 30 @ 6:30 pm"
    m = DATE_SINGLE.search(s)
    if m:
        mon = MONTHS[m.group("mon").lower()]
        day = int(m.group("day"))
        year = _infer_year(mon, day, int(m.group("year")) if m.group("year") else None)
        if m.group("stime"):
            hh, mm = _to_24(int(m.group("h")), int(m.group("m")), m.group("ampm"))
            return parse_iso_date(year, mon, day, hh, mm)
        return parse_iso_date(year, mon, day)

    # 2) "10:00 am ... October 4"
    t = TIME_THEN_DATE.search(s)
    if t:
        mon = MONTHS[t.group("mon").lower()]
        day = int(t.group("day"))
        year = _infer_year(mon, day, int(t.group("year")) if t.group("year") else None)
        hh, mm = _to_24(int(t.group("h")), int(t.group("m")), t.group("ampm"))
        return parse_iso_date(year, mon, day, hh, mm)

    # 3) "Oct 4 - Oct 5" or "October 4 - 5" -> start of range
    r = DATE_RANGE.search(s)
    if r:
        m1 = r.group("m1") or r.group("m2")
        if not m1:
            raise ValueError(f"Could not find a date in: {raw!r}")
        mon = MONTHS[m1.lower()]
        d1 = int(r.group("d1"))
        year = _infer_year(mon, d1, None)
        return parse_iso_date(year, mon, d1)

    raise ValueError(f"Could not find a date in: {raw!r}")
