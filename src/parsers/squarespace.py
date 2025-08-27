# src/parsers/squarespace.py
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse

import requests

CENTRAL_TZ = "America/Chicago"
HEADERS = {
    "User-Agent": "northwoods-events (+https://github.com/dsundt/northwoods-events)"
}

def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"

def _absolutize(base: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    return urljoin(base, href)

def _get(obj: dict, *keys, default=None):
    cur = obj
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def parse_squarespace(calendar_url: str, session: Optional[requests.Session] = None) -> List[Dict]:
    """
    Parse Squarespace calendar via ?format=json.
    Returns rows suitable for normalize_rows.
    """
    sess = session or requests.Session()
    json_url = calendar_url
    if "?" in calendar_url:
        json_url += "&format=json"
    else:
        json_url += "?format=json"

    resp = sess.get(json_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    try:
        data = resp.json()
    except Exception:
        # Some Squarespace sites return a wrapper; try to load from text
        data = json.loads(resp.text)

    # 'items' appears at data['collection']['items'] or at top-level 'items'
    items = _get(data, "collection", "items") or data.get("items") or []

    base = _origin(calendar_url)
    rows: List[Dict] = []

    for it in items:
        title = it.get("title") or it.get("headline") or ""
        if not title:
            continue

        # URL: fullUrl or url or 'fullUrl' inside item
        link = it.get("fullUrl") or it.get("url") or ""
        link = _absolutize(base, link) if link else calendar_url

        # Dates: try 'startDate', 'startDateISO', 'startDateUtc' etc.
        iso_start = it.get("startDate") or it.get("startDateISO") or it.get("startDateUtc") or None
        iso_end = it.get("endDate") or it.get("endDateISO") or it.get("endDateUtc") or None

        # Some sites use nested 'startDate' in 'startDate' -> {'iso': ...}
        if isinstance(iso_start, dict):
            iso_start = iso_start.get("iso") or iso_start.get("date") or None
        if isinstance(iso_end, dict):
            iso_end = iso_end.get("iso") or iso_end.get("date") or None

        # Location: may be inside structured content or 'location'
        location = it.get("location") or ""
        if not location:
            # try structuredContent -> location or address
            sc = it.get("structuredContent") or {}
            location = _get(sc, "location", "address") or _get(sc, "location") or ""

        # Also construct a helpful human date_text fallback
        dt_txt = ""
        if iso_start:
            dt_txt = f"{iso_start}"
            if iso_end:
                dt_txt += f" – {iso_end}"

        rows.append({
            "title": str(title).strip(),
            "date_text": dt_txt,
            "iso_hint": iso_start,
            "iso_end_hint": iso_end,
            "location": str(location).strip(),
            "url": link,
            "source": json_url,
            "tzname": CENTRAL_TZ,
        })

    return rows
