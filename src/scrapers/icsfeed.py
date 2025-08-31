from typing import List, Dict
import requests
from ics import Calendar
from datetime import timezone
import dateparser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0; +https://github.com/dsundt/northwoods-events)"
}

def scrape(ics_url: str, name: str, tzname: str, limit: int = 500) -> List[Dict]:
    r = requests.get(ics_url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    cal = Calendar(r.text)

    out: List[Dict] = []
    for i, ev in enumerate(cal.events):
        if i >= limit:
            break
        start = ev.begin
        end = ev.end
        # ensure timezone-aware (fallback to tzname if naive)
        start_iso = None
        end_iso = None
        if start:
            if start.tzinfo is None:
                parsed = dateparser.parse(str(start), settings={"TIMEZONE": tzname, "RETURN_AS_TIMEZONE_AWARE": True})
                start_iso = parsed.isoformat() if parsed else None
            else:
                start_iso = start.astimezone(timezone.utc).isoformat()
        if end:
            if end.tzinfo is None:
                parsed = dateparser.parse(str(end), settings={"TIMEZONE": tzname, "RETURN_AS_TIMEZONE_AWARE": True})
                end_iso = parsed.isoformat() if parsed else None
            else:
                end_iso = end.astimezone(timezone.utc).isoformat()

        out.append({
            "title": (ev.name or "Untitled").strip(),
            "start": start_iso,
            "end": end_iso,
            "location": ev.location,
            "url": getattr(ev, "url", None),
            "description": (ev.description or "")[:1000] if getattr(ev, "description", None) else None,
            "source": name,
            "source_kind": "ICS",
            "source_url": ics_url,
        })
    return out
