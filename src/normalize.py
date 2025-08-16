import re, pytz
from dateutil import parser as dp
from datetime import timedelta

MONTHS = "(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"

def clean_text(s):
    return re.sub(r"\s+", " ", (s or "").strip())

def parse_datetime_range(text, tzname, default_minutes):
    """
    Accepts forms like:
      'Aug 24, 2025 @ 5:00 pm – 7:00 pm'
      'August 24, 2025'
      'Aug 24–Aug 26, 2025'
    Returns: (start_dt, end_dt, all_day:bool)
    """
    text = clean_text(text)
    tz = pytz.timezone(tzname)

    # try time range same day
    m = re.search(rf"{MONTHS}\w*\s+\d{{1,2}},\s*\d{{4}}.*?(\d{{1,2}}:\d{{2}}\s*[ap]m).+?(\d{{1,2}}:\d{{2}}\s*[ap]m)", text, re.I)
    if m:
        # take first date in the string
        date_match = re.search(rf"{MONTHS}\w*\s+\d{{1,2}},\s*\d{{4}}", text, re.I)
        day = dp.parse(date_match.group(0))
        start = tz.localize(dp.parse(f"{day.strftime('%Y-%m-%d')} {m.group(1)}"))
        end = tz.localize(dp.parse(f"{day.strftime('%Y-%m-%d')} {m.group(2)}"))
        return start, end, False

    # single datetime with start only
    m = re.search(rf"{MONTHS}\w*\s+\d{{1,2}},\s*\d{{4}}(?:\s*@\s*(\d{{1,2}}:\d{{2}}\s*[ap]m))?", text, re.I)
    if m:
        day = dp.parse(m.group(0), fuzzy=True)
        if m.group(1):
            start = tz.localize(dp.parse(f"{day.strftime('%Y-%m-%d')} {m.group(1)}"))
            end = start + timedelta(minutes=default_minutes)
            return start, end, False
        # all-day
        start = tz.localize(dp.parse(day.strftime("%Y-%m-%d")))
        end = start + timedelta(days=1)
        return start, end, True

    # multi-day (rough): 'Aug 24–Aug 26, 2025'
    m = re.search(rf"({MONTHS}\w*\s+\d{{1,2}})\s*[–-]\s*({MONTHS}\w*\s+\d{{1,2}}),\s*(\d{{4}})", text, re.I)
    if m:
        start_day = dp.parse(f"{m.group(1)}, {m.group(3)}")
        end_day = dp.parse(f"{m.group(2)}, {m.group(3)}")
        start = tz.localize(dp.parse(start_day.strftime("%Y-%m-%d")))
        end = tz.localize(dp.parse(end_day.strftime("%Y-%m-%d"))) + timedelta(days=1)
        return start, end, True

    # fallback: parse anything dp can find, treat as all-day
    try:
        day = tz.localize(dp.parse(text, fuzzy=True))
        start = tz.localize(dp.parse(day.strftime("%Y-%m-%d")))
        end = start + timedelta(days=1)
        return start, end, True
    except Exception:
        return None, None, None
