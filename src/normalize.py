import re
import pytz
from dateutil import parser as dp
from datetime import timedelta, date

MONTHS = "(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"

def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def parse_datetime_range(text: str, tzname: str, default_minutes: int, iso_hint=None, iso_end_hint=None):
    """
    Returns (start_dt, end_dt, all_day)
    Strategy:
      1) If ISO hints provided (from <time datetime> or JSON-LD), use those.
      2) Else parse visible text, supporting common Modern Tribe / GrowthZone formats.
    """
    tz = pytz.timezone(tzname)

    # 1) ISO fast path
    if iso_hint:
        try:
            start = dp.parse(iso_hint)
            if not start.tzinfo:
                start = tz.localize(start)
            if iso_end_hint:
                end = dp.parse(iso_end_hint)
                if not end.tzinfo:
                    end = tz.localize(end)
                return start, end, False
            return start, start + timedelta(minutes=default_minutes), False
        except Exception:
            pass

    # 2) Text parsing
    if text:
        text = clean_text(text)
        text = text.replace("–", "-").replace("—", "-").replace("@", "")

        # Same-day with explicit time range + year
        m = re.search(rf"{MONTHS}\w*\s+\d{{1,2}},\s*\d{{4}}.*?(\d{{1,2}}:\d{{2}}\s*[ap]m).+?(\d{{1,2}}:\d{{2}}\s*[ap]m)", text, re.I)
        if m:
            dmatch = re.search(rf"{MONTHS}\w*\s+\d{{1,2}},\s*\d{{4}}", text, re.I)
            day = dp.parse(dmatch.group(0))
            start = tz.localize(dp.parse(f"{day:%Y-%m-%d} {m.group(1)}"))
            end = tz.localize(dp.parse(f"{day:%Y-%m-%d} {m.group(2)}"))
            return start, end, False

        # With start time only + year
        m = re.search(rf"({MONTHS}\w*\s+\d{{1,2}},\s*\d{{4}})\s+(\d{{1,2}}:\d{{2}}\s*[ap]m)", text, re.I)
        if m:
            day = dp.parse(m.group(1))
            start = tz.localize(dp.parse(f"{day:%Y-%m-%d} {m.group(2)}"))
            return start, start + timedelta(minutes=default_minutes), False

        # Yearless like "Aug 24 5:00 pm" or "Aug 24"
        m = re.search(rf"({MONTHS}\w*\s+\d{{1,2}})(?:\s+(\d{{1,2}}:\d{{2}}\s*[ap]m))?", text, re.I)
        if m:
            yr = date.today().year
            day = dp.parse(f"{m.group(1)} {yr}")
            if m.group(2):
                start = tz.localize(dp.parse(f"{day:%Y-%m-%d} {m.group(2)}"))
                return start, start + timedelta(minutes=default_minutes), False
            # all-day
            start = tz.localize(dp.parse(day.strftime("%Y-%m-%d")))
            return start, start + timedelta(days=1), True

        # Multi-day like "Aug 24 - Aug 26, 2025"
        m = re.search(rf"({MONTHS}\w*\s+\d{{1,2}})\s*-\s*({MONTHS}\w*\s+\d{{1,2}}),\s*(\d{{4}})", text, re.I)
        if m:
            sday = dp.parse(f"{m.group(1)}, {m.group(3)}")
            eday = dp.parse(f"{m.group(2)}, {m.group(3)}")
            start = tz.localize(dp.parse(sday.strftime("%Y-%m-%d")))
            end = tz.localize(dp.parse(eday.strftime("%Y-%m-%d"))) + timedelta(days=1)
            return start, end, True

        # Fallback: let dateutil guess; treat as all-day
        try:
            d = dp.parse(text, fuzzy=True)
            if not d.tzinfo:
                d = tz.localize(d)
            start = tz.localize(dp.parse(d.strftime("%Y-%m-%d")))
            end = start + timedelta(days=1)
            return start, end, True
        except Exception:
            pass

    return None, None, None
