from ics import Calendar
from dateutil import tz

def parse(ics_text: str):
    """
    Parse an .ics string into our common event dicts.
    Returns list of dicts with keys:
      title, url, date_text, venue_text, iso_datetime, iso_end
    """
    items = []
    cal = Calendar(ics_text)
    # normalize to local if tzinfo missing
    local_tz = tz.tzlocal()

    for ev in cal.events:
        title = (ev.name or "").strip()
        url = ""
        # Try to find a URL in description if present
        if ev.description:
            # simple heuristic: last 'http' chunk
            for token in str(ev.description).split():
                if token.startswith("http"):
                    url = token.strip()
        start = ev.begin.datetime if ev.begin else None
        end = ev.end.datetime if ev.end else None

        if start and not start.tzinfo:
            start = start.replace(tzinfo=local_tz)
        if end and not end.tzinfo:
            end = end.replace(tzinfo=local_tz)

        items.append({
            "title": title,
            "url": url,
            "date_text": "",         # not needed when we have ISO
            "venue_text": (ev.location or "").strip(),
            "iso_datetime": start.isoformat() if start else None,
            "iso_end": end.isoformat() if end else None,
        })
    return items
