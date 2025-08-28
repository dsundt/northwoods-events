# src/utils/jsonld.py
from __future__ import annotations
from typing import Any, Dict, Iterable, List

import json

def extract_events_from_jsonld(soup) -> List[Dict[str, Any]]:
    """Return a list of dicts for any JSON-LD @type Event blocks found on the page."""
    out: List[Dict[str, Any]] = []
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue

        def _iter(obj: Any) -> Iterable[Dict[str, Any]]:
            if isinstance(obj, dict):
                if obj.get("@type") in ("Event", ["Event"]):
                    yield obj
                for v in obj.values():
                    yield from _iter(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from _iter(v)

        for ev in _iter(data):
            out.append(ev)
    return out
