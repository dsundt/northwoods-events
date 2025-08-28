from __future__ import annotations
import re
from datetime import datetime, date
from typing import Tuple, Optional

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

_MWORD = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
# Require true word boundaries to avoid matching "Mar" in "Market"
_M = rf"\b{_MWORD}\b"
_TIME = r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>am|pm)"

# August 2 @ 10:00 am  |  Aug 2, 2025 10:00 am  |  August 2
DATE1 = re.compile(
    rf"(?P<mon>{_M})\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?"
    rf"(?:\s*(?:@|,)?\s*(?P<stime>{_TIME}))?",
    re.I,
)

# October 4 - October 5  |  Oct 4 - 5
DRANGE = re.compile(
    rf"(?P<m1>{_M})?\s*(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<m2>{_M})?\s*(?P<d2>\d{{1,2}})",
    re.I,
)

def _infer_year(mon: int, day: int, year: Optional[int]) -> int:
    if year:
        return year
    today = date.today()
    candidate = date(today.year, mon, day)
    # Push obviously past listings into the next year
    if (candidate - today).days < -300:
        return today.year + 1
    return today.year

def _to24(h: int, m: int, ampm: str) -> Tuple[int, int]:
    h = h % 12
    if ampm.lower() == "pm":
        h += 12
    return h, m

def parse_datetime_range(raw: str) -> str:
    """Return ISO8601 start datetime. Raises ValueError on failure."""
    s = (raw or "").strip()
    if not s:
        raise ValueError(f"Could not find a date in: {raw!r}")

    m = DATE1.search(s)
    if m:
        mon = MONTHS[m.group("mon").lower()]
        day = int(m.group("day"))
        year = _infer_year(mon, day, int(m.group("year")) if m.group("year") else None)
        if m.group("stime"):
            h = int(m.group("h")); mm = int(m.group("m"))
            h, mm = _to24(h, mm, m.group("ampm"))
            dt = datetime(year, mon, day, h, mm)
        else:
            dt = datetime(year, mon, day)
        return dt.isoformat()

    r = DRANGE.search(s)
    if r:
        m1 = r.group("m1") or r.group("m2")
        if not m1:
            raise ValueError(f"Could not find a date in: {raw!r}")
        mon = MONTHS[m1.lower()]
        d1 = int(r.group("d1"))
        year = _infer_year(mon, d1, None)
        return datetime(year, mon, d1).isoformat()

    raise ValueError(f"Could not find a date in: {raw!r}")
