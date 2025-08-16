from datetime import timedelta
from ics import Calendar, Event

def build_ics(events, path: str):
    """
    events: list of dicts {
      title, description, location, url, start (aware dt), end (aware dt), all_day (bool)
    }
    Guarantees end > start to satisfy ics library constraints.
    """
    cal = Calendar()
    for e in events:
        # Skip if required fields missing
        if not e.get("title") or not e.get("start") or not e.get("end"):
            continue

        ev = Event()
        ev.name = e["title"]

        body = e.get("description") or ""
        if e.get("url"):
            body = (body + "\n\nSource: " + e["url"]).strip()
        ev.description = body or None

        ev.location = e.get("location") or None

        if e.get("all_day"):
            b = e["start"].date()
            en = e["end"].date()
            if en <= b:
                # ensure at least one full day
                en = (e["start"] + timedelta(days=1)).date()
            ev.begin = b
            ev.end = en
        else:
            b = e["start"]
            en = e["end"]
            if en <= b:
                # ensure at least +1 minute; choose +60m for a meaningful slot
                en = b + timedelta(minutes=60)
            ev.begin = b
            ev.end = en

        cal.events.add(ev)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(cal)
