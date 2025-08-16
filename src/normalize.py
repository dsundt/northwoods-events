import re, pytz
from dateutil import parser as dp
from datetime import timedelta

MONTHS = "(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"

def clean_text(s):
    return re.sub(r"\s+", " ", (s or "").strip())

def parse_datetime_range(text, tzname, default_minutes, iso_hint=None):
    """
    Accepts:
      - ISO hint from <time datetime="..."> when present
      - 'Aug 24, 2025 @ 5:00 pm – 7:00 pm'
      - 'August 24, 2025'
      - 'Aug 24–Aug 26, 2025'
      - 'Aug 24 @ 5:00 pm' (no year -> assume current year)
    Returns: (start_dt, end_dt, all_day:bool) in tzname
    """
    tz = pytz.timezone(tzname)

    # 1) Fast path if we have a machine-readable ISO from the page
    if iso_hint:
        try:
            start = dp.parse(iso_hint)
            if not start.tzinfo:
                start = tz.localize(start)
            end = start + timedelta(minutes=default_minutes)
            return start, end, False
        except Exception:
            pass

    text = clean_text(text)

    # Normalize separators
    text = text.replace("–", "-").replace("—", "-").replace("@", "")

    # time range same day with year
    m = re.search(rf"{MONTHS}\w*\s+\d{{1,2}},\s*\d{{4}}.*?(\d{{1,2}}:\d{{2}}\s*[ap]m).+?(\d{{1,2}}:\d{{2}}\s*[ap]m)", text, re.I)
    if m:
        date_match = re.search(rf"{MONTHS}\w*\s+\d{{1,2}},\s*\d{{4}}", text, re.I)
        day = dp.parse(date_match.group(0))
        start = tz.localize(dp.parse(f"{day:%Y-%m-%d} {m.group(1)}"))
        end = tz.localize(dp.parse(f"{day:%Y-%m-%d} {m.group(2)}"))
        return start, end, False

    # with start time only (has year)
    m = re.search(rf"({MONTHS}\w*\s+\d{{1,2}},\s*\d{{4}})\s+(\d{{1,2}}:\d{{2}}\s*[ap]m)", text, re.I)
    if m:
        day = dp.parse(m.group(1))
        start = tz.localize(dp.parse(f"{day:%Y-%m-%d} {m.group(2)}"))
        return start, start + timedelta(minutes=default_minutes), False

    # yearless forms like 'Aug 24 5:00 pm' or 'Aug 24'
    m = re.search(rf"({MONTHS}\w*\s+\d{{1,2}})(?:\s+(\d{{1,2}}:\d{{2}}\s*[ap]m))?", text, re.I)
    if m:
        # assume current year
        from datetime import date
        yr = date.today().year
        day = dp.parse(f"{m.group(1)} {yr}")
        if m.group(2):
            start = tz.localize(dp.parse(f"{day:%Y-%m-%d} {m.group(2)}"))
            return start, start + timedelta(minutes=default_minutes), False
        start = tz.localize(dp.parse(day.strftime("%Y-%m-%d")))
        return start, start + timedelta(days=1), True

    # multi-day like 'Aug 24 - Aug 26, 2025'
    m = re.search(rf"({MONTHS}\w*\s+\d{{1,2}})\s*-\s*({MONTHS}\w*\s+\d{{1,2}}),\s*(\d{{4}})", text, re.I)
    if m:
        start_day = dp.parse(f"{m.group(1)}, {m.group(3)}")
        end_day = dp.parse(f"{m.group(2)}, {m.group(3)}")
        start = tz.localize(dp.parse(start_day.strftime("%Y-%m-%d")))
        end = tz.localize(dp.parse(end_day.strftime("%Y-%m-%d"))) + timedelta(days=1)
        return start, end, True

    # fallback: let dateutil guess, then treat as all-day
    try:
        day = dp.parse(text, fuzzy=True)
        if not day.tzinfo:
            day = tz.localize(day)
        start = tz.localize(dp.parse(day.strftime("%Y-%m-%d")))
        end = start + timedelta(days=1)
        return start, end, True
    except Exception:
        return None, None, None
