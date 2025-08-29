# src/state_store.py
from __future__ import annotations

import json
from datetime import datetime
from dateutil import parser as dp

def load_events(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def save_events(store: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)

def merge_events(store: dict, new_events: list[dict], now: datetime) -> dict:
    store = dict(store or {})
    for e in new_events or []:
        sid = e.get("sid")
        if not sid:
            # tolerate missing sid by constructing one from required fields
            base = (e.get("title", "") + e.get("start_iso", "") + e.get("url", "") + e.get("location", ""))
            import hashlib
            sid = hashlib.md5(base.encode("utf-8")).hexdigest()
            e["sid"] = sid
        rec = dict(store.get(sid, {}))
        rec.update({
            "title": e.get("title", ""),
            "description": e.get("description", ""),
            "location": e.get("location", ""),
            "url": e.get("url", ""),
            "start_iso": e.get("start_iso", ""),
            "end_iso": e.get("end_iso", ""),
            "all_day": bool(e.get("all_day", False)),
            "source": e.get("source", ""),
            "last_seen": now.isoformat(),
        })
        store[sid] = rec
    return store

def to_runtime_events(store: dict) -> list[dict]:
    out = []
    for sid, e in (store or {}).items():
        try:
            start = dp.parse(e.get("start_iso", ""))
            end = dp.parse(e.get("end_iso", ""))
        except Exception:
            continue
        out.append({
            "title": e.get("title", ""),
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
