# src/parse_ics.py
from __future__ import annotations
import requests
from typing import List, Dict, Any, Optional
from ics import Calendar
from datetime import datetime
import pytz
from .utils import norm_event, save_debug_html

UA = "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0; +https://example.invalid)"

def parse_ics(name: str, url: str, tzname: Optional[str] = None) -> List[Dict[str, Any]]:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    if r.status_code == 404:
        # known transient for Presque Isle; return empty but don't crash pipeline
        return []
    r.raise_for_status()
    text = r.text
    # keep a copy for debugging
    save_debug_html(text, filename=f"ics_{name.replace(' ','_')}", subdir="ics")
    cal = Calendar(text)
    tz = pytz.timezone(tzname) if tzname else None
    out: List[Dict[str, Any]] = []
    for e in cal.events:
        start = e.begin
        end = e.end
        if tz:
            # if naive, localize
            if start and start.tzinfo is None:
                start = tz.localize(start)
            if end and end.tzinfo is None:
                end = tz.localize(end)
        out.append(norm_event({
            "title": e.name or "",
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "url": (e.url or "").strip(),
            "location": (e.location or "").strip(),
            "source": name,
        }))
    return out
