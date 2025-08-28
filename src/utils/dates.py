from __future__ import annotations
import re
from datetime import datetime, date
from typing import Tuple, Optional

# Public API
__all__ = ["parse_datetime_range", "looks_like_iso", "try_parse_datetime_range"]

# Month map supports short/long names and "Sept"
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

# Regex pieces
_M = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
_TIME = r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm>am|pm)"
# e.g. "Aug 31, 2025 10:00 am", "August 30 @ 6:30 pm", "Aug 31 10:00 am"
_DATE1 = re.compile(
    rf"(?P<mon>{_M})\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?"
    rf"(?:\s*(?:@|,)?\s*(?P<stime>{_TIME}))?",
    re.IGNORECASE,
)
# e.g. "Oct 4 - Oct 5", "October 4 - 5"
_RANGE = re.compile(
    rf"(?P<m1>{_M})?\s*(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<m2>{_M})?\s*(?P<d2>\d{{1,2}})",
    re.IGNORECASE,
)

# Common header words to ignore (defensive)
_HEADER_WORDS = {"events", "featured events", "upcoming events", "view calendar"}

def _infer_year(mon: int, day: int, year: Optional[int]) -> int:
    if year:
        return year
    today = date.today()
    candidate = date(today.year, mon, day)
    # If candidate is ~last season, bump a year (site often lists fall events in early year)
    if (candidate - today).days < -300:
        return today.year + 1
    return today.year

def _to_24(h: int, m: int, ampm: str) -> Tuple[int, int]:
    ampm = ampm.lower()
    h = h % 12
    if ampm == "pm":
        h += 12
    return h, m

def looks_like_iso(s: str) -> bool:
    """Cheap check: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'."""
    if not s or not isinstance(s, str):
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(:\d{2})?)?$", s))

def _clean(raw: str) -> str:
    raw = (raw or "").strip()
    # Strip obvious headers to avoid false positives
    if raw.lower() in _HEADER_WORDS:
        return ""
    # Collapse whitespace
    return re.sub(r"\s+", " ", raw)

def parse_datetime_range(raw: str) -> str:
    """
    Parse forgiving event date strings commonly found on Modern Tribe / GrowthZone / Simpleview pages:
      - "August 30 @ 6:30 pm - 8:30 pm"
      - "Oct 4 - Oct 5" or "October 4 - 5"
      - "Aug 31, 2025 10:00 am"
    Returns ISO8601 start datetime (local-naive). Raises ValueError if no concrete date found.
    """
    raw = _clean(raw)
    if not raw:
        raise ValueError(f"Could not find a date in: {raw!r}")

    # 1) Full single date with optional time
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

    # 2) Day range (we return the START)
    r = _RANGE.search(raw)
    if r:
        m1 = r.group("m1") or r.group("m2")
        # If neither month is present, we cannot infer a real date safely
        if not m1:
            raise ValueError(f"Could not find a date in: {raw!r}")
        mon1 = MONTHS[m1.lower()]
        d1 = int(r.group("d1"))
        year = _infer_year(mon1, d1, None)
        dt = datetime(year, mon1, d1)
        return dt.isoformat()

    # 3) Time-only strings (e.g., "10:00 am") are NOT accepted here — raise
    #    The caller can choose to skip or try to supply an external date hint.
    raise ValueError(f"Could not find a date in: {raw!r}")

def try_parse_datetime_range(raw: str) -> Optional[str]:
    """Safe wrapper that returns None instead of raising."""
    try:
        return parse_datetime_range(raw)
    except Exception:
        return None
