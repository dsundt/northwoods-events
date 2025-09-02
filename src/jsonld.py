# src/utils/jsonld.py
from __future__ import annotations
import json, re
from typing import Dict, Iterable, List, Any, Optional
from dateutil.parser import isoparse
from datetime import datetime
import pytz

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)

def _load_json_candidates(html: str) -> Iterable[Any]:
    for m in _JSONLD_RE.finditer(html or ""):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            # Some sites concatenate multiple JSON objects without a wrapping array.
            # Try strict first, then a naive "split }{"
            yield json.loads(raw)
        except Exception:
            try:
                parts = []
                depth = 0
                buf = []
                for ch in raw:
                    buf.append(ch)
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            parts.append("".join(buf))
                            buf = []
                for p in parts:
                    yield json.loads(p)
            except Exception:
                continue

def _iter_graph(nodes: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(nodes, dict):
        yield nodes
        # @graph may contain events
        if "@graph" in nodes and isinstance(nodes["@graph"], list):
            for n in nodes["@graph"]:
                if isinstance(n, dict):
                    yield n
    elif isinstance(nodes, list):
        for n in nodes:
            if isinstance(n, dict):
                yield n

def _as_tzaware(dt: Any, default_tz: Optional[str]) -> Optional[str]:
    if not dt:
        return None
    try:
        d = isoparse(str(dt))
        if d.tzinfo is None and default_tz:
            tz = pytz.timezone(default_tz)
            d = tz.localize(d)
        return d.isoformat()
    except Exception:
        return None

def _string(x: Any) -> Optional[str]:
    if isinstance(x, str):
        return x.strip()
    return None

def _event_location(loc: Any) -> str:
    # Try common JSON-LD structures for Event.location
    if isinstance(loc, str):
        return loc.strip()
    if isinstance(loc, dict):
        nm = loc.get("name")
        if isinstance(nm, str) and nm.strip():
            return nm.strip()
        addr = loc.get("address")
        if isinstance(addr, dict):
            parts = [addr.get(k) for k in ("name","streetAddress","addressLocality","addressRegion")]
            parts = [p for p in parts if isinstance(p, str) and p.strip()]
            if parts:
                return ", ".join(parts)
        if "@type" in loc and "name" in loc and isinstance(loc["name"], str):
            return loc["name"].strip()
    return ""

def extract_events_from_jsonld(
    html: str,
    source_name: str = "",
    default_tz: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Parse Event objects from any JSON-LD in the page.
    Returns a list of normalized dicts with keys:
      title, start, end, url, location, source
    """
    out: List[Dict[str, Any]] = []
    for blob in _load_json_candidates(html):
        for node in _iter_graph(blob):
            types = node.get("@type")
            if isinstance(types, list):
                is_event = any(t.lower() == "event" for t in (x.lower() for x in types if isinstance(x, str)))
            else:
                is_event = isinstance(types, str) and types.lower() == "event"
            if not is_event:
                continue

            title = _string(node.get("name")) or ""
            start = _as_tzaware(node.get("startDate"), default_tz)
            end = _as_tzaware(node.get("endDate"), default_tz)
            url = _string(node.get("url")) or ""
            location = _event_location(node.get("location"))

            if not title or not start:
                # Minimal requirements
                continue

            out.append({
                "title": title,
                "start": start,
                "end": end,
                "url": url,
                "location": location,
                "source": source_name,
            })
    return out
