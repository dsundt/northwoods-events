# src/parse_ics.py
from ics import Calendar
from .fetch import fetch_text
from datetime import datetime
from dateutil import tz

def parse_ics(source_name: str, url: str, tzname: str | None = None):
    """
    Yield dict events from an ICS feed.
    Guaranteed fields: title, start, end, location, source, url
    """
    raw = fetch_text(url=url)  # be explicit: url=
    cal = Calendar(raw)

    local_tz = tz.gettz(tzname) if tzname else tz.UTC

    def ensure_dt(dt):
        if not dt:
            return None
        if isinstance(dt, datetime):
            d = dt
        else:
            d = dt.datetime if hasattr(dt, "datetime") else None
        if not d:
            return None
        # If floating or naive, attach provided tz
        if d.tzinfo is None:
            d = d.replace(tzinfo=local_tz)
        return d.astimezone(tz.UTC)

    for ev in cal.events:
        title = (ev.name or "").strip()
        start = ensure_dt(ev.begin)
        end = ensure_dt(ev.end)
        # Drop entries that still have no start
        if not start:
            continue
        yield {
            "title": title or "(untitled)",
            "start": start.isoformat(),
            "end": end.isoformat() if end else None,
            "location": (getattr(ev, "location", None) or "").strip() or None,
            "source": source_name,
            "url": url,
        }
