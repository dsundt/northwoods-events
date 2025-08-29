# src/parse_ics.py
from __future__ import annotations

from dateutil import parser as dp
from ics import Calendar

from .fetch import fetch_text
from .normalize import normalize_event

def parse_ics(source, add_event):
    url = source["url"]
    text = fetch_text(url)
    cal = Calendar(text)

    for e in cal.events:
        title = (e.name or "").strip()
        link = (e.url or "").strip()
        loc = (e.location or "").strip()
        desc = (e.description or "").strip()

        start = e.begin.datetime if e.begin else None
        end = e.end.datetime if e.end else None
        all_day = bool(getattr(e, "all_day", False))

        evt = normalize_event(
            title=title,
            url=link,
            where=loc,
            start=start,
            end=end,
            tzname=source.get("tzname"),
            description=desc,
            all_day=all_day,
            source_name=source.get("name"),
        )
        if evt:
            add_event(evt)
