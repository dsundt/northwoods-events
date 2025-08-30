# src/parse_ics.py
from __future__ import annotations

from ics import Calendar
from .normalize import normalize_event, parse_dt, clean_text
from .fetch import fetch_text

def parse_ics(source, add_event):
    url = source["url"]
    tzname = source.get("tzname")
    ics_text = fetch_text(url, source=source)
    if not ics_text:
        return
    try:
        cal = Calendar(ics_text)
    except Exception:
        return

    for ve in cal.events:
        title = clean_text(ve.name or "")
        if not title:
            continue
        # ics Event.begin/end may be arrow objects; normalize via parse_dt for consistency
        start_iso = (ve.begin.to('UTC').isoformat() if getattr(ve, "begin", None) else "") or ""
        end_iso   = (ve.end.to('UTC').isoformat()   if getattr(ve, "end", None)   else "") or ""

        evt = normalize_event(
            title=title,
            url=getattr(ve, "url", None) or url,
            where=clean_text(getattr(ve, "location", "") or ""),
            start=parse_dt(start_iso, tzname),
            end=parse_dt(end_iso, tzname) if end_iso else None,
            tzname=tzname,
            description=clean_text(getattr(ve, "description", "") or "")
        )
        if evt:
            add_event(evt)
