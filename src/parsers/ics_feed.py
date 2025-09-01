from __future__ import annotations
from typing import List, Dict, Any, Optional
from ics import Calendar
import arrow

def _iso(dt) -> Optional[str]:
    if not dt:
        return None
    try:
        # dt may be an Arrow object or datetime
        return dt.to("utc").isoformat() if hasattr(dt, "to") else dt.astimezone().isoformat()
    except Exception:
        try:
            return dt.isoformat()
        except Exception:
            return None

def parse_ics(text: str, tzname: Optional[str], source_name: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cal = Calendar(text)
    for e in cal.events:
        title = (e.name or "").strip()
        start = _iso(e.begin)
        end   = _iso(e.end)
        loc   = (e.location or "").strip()
        url   = (e.url or "").strip() or None
        if title and start:
            out.append({
                "title": title,
                "start": start,
                "end": end,
                "location": loc,
                "url": url,
                "source": source_name,
            })
    return out
