# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from dateutil import parser as duparser

def _ensure_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

def _first_text(x: Any) -> str:
    if isinstance(x, dict):
        return x.get("name") or x.get("title") or ""
    if isinstance(x, list):
        for item in x:
            t = _first_text(item)
            if t:
                return t
        return ""
    return str(x or "").strip()

def _extract_url(obj: Any) -> str:
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, dict):
        return obj.get("url") or obj.get("@id") or ""
    return ""

def _flatten_location(loc: Any) -> str:
    # Handles Place -> name/address, or plain strings
    if not loc:
        return ""
    if isinstance(loc, str):
        return loc.strip()
    if isinstance(loc, dict):
        parts = []
        nm = loc.get("name")
        if nm:
            parts.append(nm)
        addr = loc.get("address")
        if isinstance(addr, str):
            parts.append(addr)
        elif isinstance(addr, dict):
            addr_parts = [
                addr.get("streetAddress"),
                addr.get("addressLocality"),
                addr.get("addressRegion"),
                addr.get("postalCode"),
                addr.get("addressCountry"),
            ]
            parts.append(", ".join([p for p in addr_parts if p]))
        return ", ".join([p for p in parts if p])
    return ""

def _parse_dt(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        return duparser.isoparse(s).isoformat()
    except Exception:
        # Sometimes JSON-LD dates are not perfect ISO; let dateutil try again
        try:
            return duparser.parse(s, fuzzy=True).isoformat()
        except Exception:
            return None

def extract_events_from_ldjson(html: str) -> List[Dict[str, Any]]:
    """
    Scan <script type="application/ld+json"> blocks and collect schema.org Event items.
    Returns a list of dicts with: title, start_iso, end_iso, url, location.
    """
    out: List[Dict[str, Any]] = []
    soup = BeautifulSoup(html or "", "lxml")

    scripts = soup.find_all("script", attrs={"type": re.compile(r"^application/ld\+json$", re.I)})
    for s in scripts:
        txt = (s.string or s.get_text() or "").strip()
        if not txt:
            continue
        # Some sites concatenate multiple JSON objects or wrap in arrays
        candidates: List[Any] = []
        try:
            data = json.loads(txt)
            candidates.extend(_ensure_list(data))
        except Exception:
            # Try to salvage by extracting {...} chunks (very forgiving)
            for m in re.finditer(r"\{.*?\}", txt, flags=re.S):
                try:
                    candidates.append(json.loads(m.group(0)))
                except Exception:
                    pass

        for node in candidates:
            # Walk structures that use @graph
            if isinstance(node, dict) and "@graph" in node:
                for g in _ensure_list(node.get("@graph")):
                    _collect_if_event(g, out)
            else:
                _collect_if_event(node, out)
    return out

def _collect_if_event(node: Any, out: List[Dict[str, Any]]) -> None:
    if not isinstance(node, dict):
        return
    t = node.get("@type")
    types = _ensure_list(t)
    types = [str(x) for x in types]
    if not any(tp.lower() == "event" for tp in types):
        return
    title = node.get("name") or node.get("headline") or ""
    start_iso = _parse_dt(node.get("startDate"))
    end_iso = _parse_dt(node.get("endDate"))
    url = _extract_url(node.get("url") or node.get("@id"))
    location = _flatten_location(node.get("location"))

    if title and start_iso:
        out.append({
            "title": title.strip(),
            "start_iso": start_iso,
            "end_iso": end_iso,
            "url": (url or "").strip(),
            "location": location.strip(),
        })
