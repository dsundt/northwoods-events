#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Northwoods Events builder (drop-in).
Adds special handling for St. Germain, which loads events via AJAX.
- Fetch -> Parse -> Normalize -> Write report (+ optional ICS)
- Always writes last_run_report.json, even if fatal errors occur.
"""

from __future__ import annotations

# --- sys.path & stdlib ---
import os, sys, json, time, traceback, re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple, Optional
from urllib.parse import urlparse, urljoin

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
STATE_DIR = os.path.join(REPO_ROOT, "state")
SNAPSHOT_DIR = os.path.join(STATE_DIR, "snapshots")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# Ensure local imports work both in CI and local runs
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

# --- third-party ---
import requests  # requests is standard in GH runners; if not, add to requirements
from bs4 import BeautifulSoup

# --- project imports (your existing modules) ---
from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.municipal import parse_municipal

# If you have a models.Event dataclass, feel free to import it.
# We’ll remain in dict-normalization space to avoid import assumptions.

TZ = timezone(timedelta(hours=-5))  # America/Chicago at runtime; adjust if needed
USER_TZ_NAME = "America/Chicago"

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(TZ).isoformat()

def _snapshot_name(title: str) -> str:
    safe = title.lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9._()-]+", "_", safe)

def save_snapshot(name: str, content: str) -> str:
    path = os.path.join(SNAPSHOT_DIR, f"{_snapshot_name(name)}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def fetch_url(url: str, session: Optional[requests.Session] = None) -> Tuple[str, requests.Response]:
    sess = session or requests.Session()
    headers = {
        "User-Agent": "NorthwoodsEventsBot/1.0 (+https://example.invalid)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = sess.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text, resp

def normalize_event(
    title: str,
    start: datetime,
    end: Optional[datetime] = None,
    location: str = "",
    url: str = "",
) -> Dict[str, Any]:
    return {
        "title": title.strip(),
        "start": start.astimezone(TZ).isoformat(),
        "end": (end or start).astimezone(TZ).isoformat(),
        "location": location.strip(),
        "url": url,
    }

# -------------------------------------------------------------------
# St. Germain: AJAX-aware fetcher
# -------------------------------------------------------------------
def _extract_ajax_config(html: str, base_url: str) -> Tuple[str, Optional[str]]:
    """
    Look for a wp_localize_script-style object:
      var micronet_api_intergration_for_wordpress_ajax = { ajaxurl: "...", nonce: "..." }
    Return (ajaxurl, nonce_or_None). Fall back to wp-admin/admin-ajax.php if not embedded.
    """
    ajaxurl = urljoin(base_url, "/wp-admin/admin-ajax.php")
    nonce = None

    m = re.search(
        r"micronet_api_intergration_for_wordpress_ajax\s*=\s*\{([^}]+)\}",
        html, re.DOTALL | re.IGNORECASE
    )
    if m:
        obj = m.group(1)
        # crude extraction of key/value pairs
        kv = dict(re.findall(r'(\w+)\s*:\s*["\']([^"\']+)["\']', obj))
        ajaxurl = kv.get("ajaxurl", ajaxurl)
        nonce = kv.get("nonce")
        # Make absolute if needed
        ajaxurl = urljoin(base_url, ajaxurl)

    return ajaxurl, nonce

def st_germain_ajax(base_url: str) -> List[Dict[str, Any]]:
    """
    Hit the site's AJAX endpoint to retrieve events across pages.
    Falls back to zero if endpoint/format changes or no events are returned.
    """
    sess = requests.Session()
    page_html, _ = fetch_url(base_url, sess)
    ajaxurl, nonce = _extract_ajax_config(page_html, base_url)

    # Time window: last month through +6 months (liberal, the server will filter)
    start_date = (datetime.now(TZ) - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = (datetime.now(TZ) + timedelta(days=180)).strftime("%Y-%m-%d")

    def one_page(page_num: int) -> Dict[str, Any]:
        data = {
            "action": "mbi_filter_events",
            "page": page_num,
            "start_date": start_date,
            "end_date": end_date,
            "category": "",     # all
            "search": "",       # none
            "limit": 40,        # reasonable page size
            "order": "asc",
        }
        if nonce:
            data["nonce"] = nonce

        r = sess.post(ajaxurl, data=data, timeout=30, headers={"Referer": base_url})
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            # Some sites return HTML; try to find JSON fragment
            return {"success": False, "data": {}}

    # Pull pages until done
    normalized: List[Dict[str, Any]] = []
    page = 1
    max_pages = 15  # guardrail
    while page <= max_pages:
        payload = one_page(page)
        if not payload or not payload.get("success"):
            break
        data = payload.get("data", {})
        posts = data.get("posts") or []
        if not posts:
            break

        for p in posts:
            title = (p.get("title") or p.get("post_title") or "").strip()
            link = p.get("permalink") or p.get("url") or urljoin(base_url, "/events-calendar/")
            location_parts = [p.get("venue", ""), p.get("address", ""), p.get("city", "")]
            location = ", ".join([s for s in location_parts if s])

            # Try a handful of date field patterns commonly seen
            dt_candidates = [
                p.get("start"), p.get("start_date"), p.get("date"),
                f"{p.get('month','')} {p.get('day','')}, {p.get('year','')}".strip(),
            ]
            start_dt = None
            for cand in dt_candidates:
                if not cand:
                    continue
                try:
                    # be lenient; dateutil is available
                    from dateutil import parser as dtp
                    start_dt = dtp.parse(str(cand))
                    break
                except Exception:
                    continue

            if not title or not start_dt:
                continue  # skip malformed rows

            # End date/time (optional)
            end_dt = None
            for cand in [p.get("end"), p.get("end_date")]:
                if not cand:
                    continue
                try:
                    from dateutil import parser as dtp
                    end_dt = dtp.parse(str(cand))
                    break
                except Exception:
                    continue

            normalized.append(normalize_event(title, start_dt, end_dt, location, link))

        # pagination bookkeeping
        total = data.get("total") or len(normalized)
        current = data.get("current") or page
        if current >= data.get("pages", current):
            break
        page += 1

    return normalized

# -------------------------------------------------------------------
# Source registry
# -------------------------------------------------------------------
Source = Dict[str, Any]

SOURCES: List[Source] = [
    # Modern Tribe (The Events Calendar)
    {"name": "Vilas County (Modern Tribe)", "url": "https://vilaswi.com/events/?eventDisplay=list", "kind": "modern_tribe"},
    {"name": "Boulder Junction (Modern Tribe)", "url": "https://boulderjct.org/events/?eventDisplay=list", "kind": "modern_tribe"},
    {"name": "Eagle River Chamber (Modern Tribe)", "url": "https://eagleriver.org/events/?eventDisplay=list", "kind": "modern_tribe"},

    # St. Germain – custom AJAX loader (falls back to modern_tribe)
    {"name": "St. Germain Chamber (Modern Tribe)", "url": "https://st-germain.com/events-calendar/?eventDisplay=list", "kind": "st_germain_ajax"},

    {"name": "Sayner–Star Lake–Cloverland Chamber (Modern Tribe)", "url": "https://sayner-starlake-cloverland.org/events/", "kind": "modern_tribe"},

    # GrowthZone
    {"name": "Rhinelander Chamber (GrowthZone)", "url": "https://business.rhinelanderchamber.com/events/calendar", "kind": "growthzone"},

    # Simpleview
    {"name": "Minocqua Area Chamber (Simpleview)", "url": "https://www.minocqua.org/events/", "kind": "simpleview"},
    {"name": "Oneida County – Festivals & Events (Simpleview)", "url": "https://oneidacountywi.com/festivals-events/", "kind": "simpleview"},

    # Municipal
    {"name": "Town of Arbor Vitae (Municipal Calendar)", "url": "https://www.townofarborvitae.org/calendar/", "kind": "municipal"},
]

# -------------------------------------------------------------------
# Parser dispatch
# -------------------------------------------------------------------
def _get_parser(kind: str):
    if kind == "modern_tribe":
        return parse_modern_tribe
    if kind == "growthzone":
        return parse_growthzone
    if kind == "simpleview":
        return parse_simpleview
    if kind == "municipal":
        return parse_municipal
    if kind == "st_germain_ajax":
        # We'll return a shim that conforms to parser signature: (html_text, base_url) -> items
        def _shim(_html_text: str, base_url: str) -> List[Dict[str, Any]]:
            items = st_germain_ajax(base_url)
            if items:
                return items
            # fallback: if AJAX yielded nothing, try HTML parser
            return parse_modern_tribe(_html_text, base_url=base_url)
        return _shim
    raise ValueError(f"Unknown parser kind: {kind}")

# -------------------------------------------------------------------
# Pipeline
# -------------------------------------------------------------------
def run_pipeline(sources: List[Source]) -> Dict[str, Any]:
    from utils.text import text as _text  # your tiny helper
    report: Dict[str, Any] = {
        "when": now_iso(),
        "timezone": USER_TZ_NAME,
        "sources": [],
        "meta": {"status": "ok", "sources_file": "sources.yml"},
    }

    for src in sources:
        name, url, kind = src["name"], src["url"], src["kind"]
        row: Dict[str, Any] = {
            "name": name, "url": url, "fetched": 0, "parsed": 0, "added": 0,
            "samples": [], "http_status": None,
            "snapshot": f"state/snapshots/{_snapshot_name(name)}.html",
        }

        try:
            parser_fn = _get_parser(kind)
            # Always fetch HTML (for snapshots and fallback parsers)
            html, resp = fetch_url(url)
            row["http_status"] = resp.status_code
            row["fetched"] = 1
            snap = save_snapshot(name, html)
            # Parse
            if kind == "st_germain_ajax":
                # Special path calls AJAX internally, but still provide html to fallback
                items: List[Dict[str, Any]] = parser_fn(html, base_url=url)  # type: ignore
            else:
                items = parser_fn(html, base_url=url)  # type: ignore

            row["parsed"] = len(items)
            # Normalize pass-through: assume parser already returns normalized dicts per your existing convention.
            # If raw items are returned, adapt here.
            normalized = items

            row["added"] = len(normalized)
            row["samples"] = [
                {
                    "title": n.get("title", ""),
                    "start": n.get("start", ""),
                    "location": n.get("location", ""),
                    "url": n.get("url", ""),
                }
                for n in normalized[:3]
            ]

        except Exception as e:
            row["error"] = repr(e)
            row["traceback"] = "".join(traceback.format_exception(t_
