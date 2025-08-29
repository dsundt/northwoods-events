# src/icsbuild.py
from __future__ import annotations

from datetime import timedelta
from ics import Calendar, Event

def build_ics(events: list[dict], path: str):
    cal = Calendar()
    for e in events:
        if not e.get("title") or not e.get("start") or not e.get("end"):
            continue
        ev = Event()
        ev.name = e["title"]
        if e.get("description"):
            ev.description = e["description"]
        if e.get("location"):
            ev.location = e["location"]
        if e.get("url"):
            ev.url = e["url"]

        start = e["start"]
        end = e["end"]
        if end <= start:
            end = start + timedelta(minutes=60)
        ev.begin = start
        ev.end = end

        cal.events.add(ev)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(cal)
