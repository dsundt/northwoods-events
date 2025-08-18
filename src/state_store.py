import json
from datetime import datetime
from dateutil import parser as dp

def load_events(path: str) -> dict:
    """
    Load persistent event store from JSON.
    Returns dict keyed by sid with:
      title, description, location, url, start_iso, end_iso, all_day, source, last_seen
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def save_events(path: str, store: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, sort_keys=True)

def merge_events(store: dict, new_events: list, now_dt: datetime) -> dict:
    """
    Merge current-run events (list of dicts with datetime objs) into the persistent store.
    Upserts by sid. Removes events fully in the past (end < today 00:00).
    """
    # Upsert incoming
    for e in new_events:
        sid = e["sid"]
        store[sid] = {
            "title": e["title"],
            "description": e.get("description", ""),
            "location": e.get("location", ""),
            "url": e.get("url", ""),
            "start_iso": e["start"].isoformat(),
            "end_iso": e["end"].isoformat(),
            "all_day": bool(e.get("all_day", False)),
            "source": e.get("source", ""),
            "last_seen": now_dt.isoformat(),
        }

    # Purge past
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    to_delete = []
    for sid, e in store.items():
        try:
            end = dp.parse(e["end_iso"])
            if end < today_start:
                to_delete.append(sid)
        except Exception:
            # keep unparsable
            pass
    for sid in to_delete:
        store.pop(sid, None)

    return store

def to_runtime_events(store: dict) -> list:
    """
    Convert store entries back to runtime event dicts with datetime objects for ICS builder.
    """
    out = []
    for sid, e in store.items():
        try:
            start = dp.parse(e["start_iso"])
            end = dp.parse(e["end_iso"])
        except Exception:
            continue
        out.append({
            "title": e["title"],
            "description": e.get("description", ""),
            "location": e.get("location", ""),
            "url": e.get("url", ""),
            "start": start,
            "end": end,
            "all_day": bool(e.get("all_day", False)),
            "sid": sid,
        })
    out.sort(key=lambda x: x["start"])
    return out
