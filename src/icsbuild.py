from ics import Calendar, Event

def build_ics(events, path):
    """
    events: list of dicts {
      title, description, location, url, start (aware dt), end (aware dt), all_day(bool)
    }
    """
    cal = Calendar()
    for e in events:
        ev = Event()
        ev.name = e["title"]
        body = e.get("description") or ""
        if e.get("url"):
            body = (body + "\n\nSource: " + e["url"]).strip()
        ev.description = body or None
        ev.location = e.get("location") or None
        if e["all_day"]:
            ev.begin = e["start"].date()
            ev.end = e["end"].date()
        else:
            ev.begin = e["start"]
            ev.end = e["end"]
        cal.events.add(ev)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(cal)
