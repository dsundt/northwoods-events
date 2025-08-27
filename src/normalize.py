# src/normalize.py
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pytz
from dateutil import parser as duparser

CENTRAL_TZNAME = "America/Chicago"


def _safe_timezone(tzname: Optional[str]) -> pytz.BaseTzInfo:
    """
    Return a pytz timezone. If tzname is falsy or invalid, fall back to America/Chicago.
    """
    if not tzname:
        return pytz.timezone(CENTRAL_TZNAME)
    try:
        return pytz.timezone(tzname)
    except Exception:
        return pytz.timezone(CENTRAL_TZNAME)


def _to_local(dt: datetime, tz: pytz.BaseTzInfo) -> datetime:
    """
    Ensure datetime is timezone-aware in the given tz.
    - If dt is naive -> localize to tz
    - If dt is aware -> convert to tz
    """
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt.astimezone(tz)


def _looks_like_iso(s: Optional[str]) -> bool:
    if not s or not isinstance(s, str):
        return False
    # Very loose check: contains 'T' and digits typical of ISO-8601
    return "T" in s and re.search(r"\d{4}-\d{2}-\d{2}", s) is not None


def _parse_iso(s: str) -> datetime:
    # dateutil can parse both "YYYY-MM-DDTHH:MM:SSZ" and with offsets
    return duparser.isoparse(s)


def _parse_human_date_range(text: str, tz: pytz.BaseTzInfo) -> Tuple[datetime, datetime, bool]:
    """
    Extremely forgiving parser for strings like:
      - "August 28, 2025 @ 6:00 pm - 9:00 pm"
      - "August 28 @ 6 pm – August 29 @ 1 am"
      - "September 10, 2025"
    Heuristics:
      - If only a date -> all-day (00:00 to 23:59:59)
      - If a single time -> default 2-hour duration
      - If a time range -> use both times; if end < start on same date, assume it crosses midnight
    """
    text = (text or "").strip()
    all_day = False

    # Normalize dashes
    t = text.replace("–", "-").replace("—", "-")

    # Try to find a date at the beginning
    # We'll parse the first date we can, then look for times
    # Examples include “Aug 28, 2025”, “August 28”, etc.
    # Fallback: dateutil fuzzy parsing for a baseline date.
    try:
        base_date = duparser.parse(t, fuzzy=True, default=datetime(2000, 1, 1, 0, 0, 0))
    except Exception:
        # give up: today all-day
        base_date = datetime.now()

    # Extract times if present: forms like "6 pm", "6:30 pm", "18:00"
    times = re.findall(r"(\d{1,2}(:\d{2})?\s?(am|pm)?)", t, flags=re.IGNORECASE)
    times_clean = []
    for grp in times:
        raw = grp[0].strip()
        # Skip obvious dates like "2025" accidentally captured
        if re.fullmatch(r"\d{4}", raw):
            continue
        times_clean.append(raw)

    local_tz = tz

    if not times_clean:
        # No times at all -> treat as all-day for that date
        start = _to_local(datetime(base_date.year, base_date.month, base_date.day, 0, 0, 0), local_tz)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        all_day = True
        return start, end, all_day

    def _parse_time_on_date(tstr: str, d: datetime) -> datetime:
        # Let dateutil handle "6 pm", "6:30pm", "18:00"
        dt = duparser.parse(tstr, fuzzy=True, default=datetime(d.year, d.month, d.day, 0, 0, 0))
        return _to_local(dt, local_tz)

    if len(times_clean) == 1:
        start = _parse_time_on_date(times_clean[0], base_date)
        end = start + timedelta(hours=2)  # default 2h
        return start, end, all_day

    # Two or more times: use first two
    start = _parse_time_on_date(times_clean[0], base_date)

    # If the text also contains a second explicit date (e.g., "Aug 28 ... - Aug 29 ..."),
    # try to parse that date for the end; otherwise, assume same date and adjust if it wraps after midnight.
    second_date_match = re.search(
        r"(\bJan|\bFeb|\bMar|\bApr|\bMay|\bJun|\bJul|\bAug|\bSep|\bOct|\bNov|\bDec|\bJanuary|\bFebruary|\bMarch|\bApril|\bMay|\bJune|\bJuly|\bAugust|\bSeptember|\bOctober|\bNovember|\bDecember)\s+\d{1,2}(,\s*\d{4})?",
        t, flags=re.IGNORECASE
    )
    if second_date_match:
        try:
            end_date = duparser.parse(second_date_match.group(0), fuzzy=True,
                                      default=datetime(base_date.year, base_date.month, base_date.day))
        except Exception:
            end_date = base_date
    else:
        end_date = base_date

    end = _parse_time_on_date(times_clean[1], end_date)

    if end <= start:
        # Likely crossed midnight; add a day
        end = end + timedelta(days=1)

    return start, end, all_day


def parse_datetime_range(*args, **kwargs) -> Tuple[datetime, datetime, bool]:
    """
    Backward- and forward-compatible signature.

    Supports:
      New-style (keyword):
        parse_datetime_range(date_text="...", iso_hint="...", iso_end_hint="...", tzname="America/Chicago")
      Legacy positional (observed in older main.py):
        parse_datetime_range(date_text, iso_hint, iso_end_hint)    # tzname omitted
        parse_datetime_range(date_text, "America/Chicago", iso_hint, iso_end_hint)

    Returns: (start_dt_aware, end_dt_aware, all_day_bool)
    """
    # Normalize inputs to canonical variables
    date_text = kwargs.get("date_text")
    iso_hint = kwargs.get("iso_hint")
    iso_end_hint = kwargs.get("iso_end_hint")
    tzname = kwargs.get("tzname") or kwargs.get("tz")

    # If positional args present, map carefully
    # Cases:
    #   (date_text,)
    #   (date_text, iso_hint, iso_end_hint)  -> if arg1 looks like ISO, treat as iso_hint
    #   (date_text, tzname, iso_hint, iso_end_hint)
    if args:
        # first arg is always the human text
        date_text = args[0] if date_text is None else date_text

        if len(args) >= 2 and iso_hint is None and tzname is None:
            # Could be iso_hint OR tzname. Detect by shape.
            if _looks_like_iso(args[1]):
                iso_hint = args[1]
            else:
                tzname = args[1]

        if len(args) >= 3 and iso_end_hint is None:
            # If we already decided args[1] was tzname, then args[2] may be iso_hint
            if iso_hint is None and _looks_like_iso(args[2]):
                iso_hint = args[2]
            else:
                iso_end_hint = args[2]

        if len(args) >= 4:
            # 4th positional is definitely iso_end_hint in legacy usage
            if iso_end_hint is None and _looks_like_iso(args[3]):
                iso_end_hint = args[3]

    tz = _safe_timezone(tzname)

    # 1) Prefer exact ISO hints when present
    if iso_hint:
        try:
            start = _parse_iso(iso_hint)
            start = _to_local(start, tz)
            if iso_end_hint:
                end = _to_local(_parse_iso(iso_end_hint), tz)
            else:
                # default duration if no end was supplied
                end = start + timedelta(hours=2)
            all_day = False
            return start, end, all_day
        except Exception:
            # Fall through to human parsing if ISO fails
            pass

    # 2) Fallback to parsing human-readable date_text
    return _parse_human_date_range(date_text or "", tz)


def clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip()
    # normalize whitespace
    s = re.sub(r"\s+", " ", s)
    # strip zero-width / odd spaces
    s = s.replace("\u200b", "")
    return s
