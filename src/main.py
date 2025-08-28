#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Northwoods Events builder (drop-in).
- Loads sources from sources.yml (falls back to embedded list if missing/invalid)
- Special handling for St. Germain (AJAX endpoint via admin-ajax.php)
- Writes last_run_report.json (and state/last_run_report.json) every run
"""

from __future__ import annotations

# --- stdlib / path setup ---
import os, sys, json, traceback, re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple, Optional
from urllib.parse import urljoin

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
STATE_DIR = os.path.join(REPO_ROOT, "state")
SNAPSHOT_DIR = os.path.join(STATE_DIR, "snapshots")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

# --- third-party ---
import requests
from bs4 import BeautifulSoup
import yaml  # used to load sources.yml
from dateutil import parser as dtp  # lenient date parsing

# --- project imports ---
from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.municipal import parse_municipal

# --- timezone (serialization only; parsing should be tz-aware elsewhere) ---
USER_TZ_NAME = "America/Chicago"
TZ = timezone(timedelta(hours=-5))  # Central time; adjust if you maintain a more robust tz layer


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

def _to_sample_field(v: Any) -> str:
    """Make values JSON-safe for the samples block."""
    if isinstance(v, datetime):
        return v.astimezone(TZ).isoformat()
    return str(v) if v is not None else ""


# -------------------------------------------------------------------
# St. Germain: AJAX-aware fetcher (embedded; no separate file needed)
# -------------------------------------------------------------------
def _extract_ajax_config(html: str, base_url: str) -> Tuple[str, Optional[str]]:
    """
    Look for a localized JS config object:
      var micronet_api_intergration_for_wordpress_ajax = { ajaxurl: "...", nonce: "..." }
    Return (ajaxurl, nonce_or_None). Fall back to '/wp-admin/admin-ajax.php'.
    """
    ajaxurl = urljoin(base_url, "/wp-admin/admin-ajax.php")
    nonce = None

    m = re.search(
        r"micronet_api_intergration_for_wordpress_ajax\s*=\s*\{([^}]+)\}",
        html, re.DOTALL | re.IGNORECASE
    )
    if m:
        obj = m.group(1)
        kv = dict(re.findall(r'(\w+)\s*:\s*["\']([^"\']+)["\']', obj))
        ajaxurl = urljoin(base_url, kv.get("ajaxurl", ajaxurl))
        nonce = kv.get("nonce")

    return ajaxurl, nonce


def st_germain_ajax(base_url: str, return_debug: bool = False) -> List[Dict[str, Any]] | tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Hit St. Germain's AJAX endpoint (Micronet) to retrieve events.
    Returns items, and optionally a debug dict if return_debug=True.
    """
    debug: Dict[str, Any] = {
        "attempt": "ajax",
        "ajaxurl": None,
        "nonce_found": False,
        "pages": 0,
        "posts_total": 0,
        "success_pages": 0,
    }

    sess = requests.Session()
    page_html, _ = fetch_url(base_url, sess)
    ajaxurl, nonce = _extract_ajax_config(page_html, base_url)
    debug["ajaxurl"] = ajaxurl
    debug["nonce_found"] = bool(nonce)

    # Time window: last 30 days -> next 180 days (server will filter)
    start_date = (datetime.now(TZ) - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = (datetime.now(TZ) + timedelta(days=180)).strftime("%Y-%m-%d")

    def one_page(page_num: int) -> Dict[str, Any]:
        data = {
            "action": "mbi_filter_events",
            "page": page_num,
            "start_date": start_date,
            "end_date": end_date,
            "category": "",
            "search": "",
            "limit": 40,
            "order": "asc",
        }
        if nonce:
            data["nonce"] = nonce

        r = sess.post(ajaxurl, data=data, timeout=30, headers={"Referer": base_url})
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"success": False, "data": {}}

    normalized: List[Dict[str, Any]] = []
    page = 1
    max_pages = 15
    success_pages = 0

    while page <= max_pages:
        payload = one_page(page)
        if not payload:
            break
        if payload.get("success"):
            success_pages += 1
        data = payload.get("data", {})
        posts = data.get("posts") or []
        if not posts:
            break

        debug["pages"] = page
        debug["posts_total"] += len(posts)

        for p in posts:
            title = (p.get("title") or p.get("post_title") or "").strip()
            link = p.get("permalink") or p.get("url") or urljoin(base_url, "/events-calendar/")
            location_parts = [p.get("venue", ""), p.get("address", ""), p.get("city", "")]
            location = ", ".join([s for s in location_parts if s])

            # Try common date fields
            dt_candidates = [
                p.get("start"),
                p.get("start_date"),
                p.get("date"),
                " ".join(x for x in [p.get("month", ""), p.get("day", ""), p.get("year", "")] if x).strip(),
            ]
            start_dt = None
            for cand in dt_candidates:
                if not cand:
                    continue
                try:
                    start_dt = dtp.parse(str(cand))
                    break
                except Exception:
                    continue
            if not title or not start_dt:
                continue

            end_dt = None
            for cand in [p.get("end"), p.get("end_date")]:
                if not cand:
                    continue
                try:
                    end_dt = dtp.parse(str(cand))
                    break
                except Exception:
                    continue

            normalized.append(normalize_event(title, start_dt, end_dt, location, link))

        pages_total = data.get("pages", page)
        if page >= pages_total:
            break
        page += 1

    debug["success_pages"] = success_pages

    if return_debug:
        return normalized, debug
    return normalized


# -------------------------------------------------------------------
# Load sources from YAML (fallback to embedded list)
# -------------------------------------------------------------------
def load_sources_from_yaml(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        lst = doc.get("sources", [])
        return [s for s in lst if isinstance(s, dict) and "url" in s and "kind" in s and "name" in s]
    except Exception:
        return []


Source = Dict[str, Any]

# Prefer sources.yml; fallback to embedded list if missing/invalid
YAML_SOURCES = load_sources_from_yaml(os.path.join(REPO_ROOT, "sources.yml"))
SOURCES: List[Source] = YAML_SOURCES or [
    {"name": "Vilas County (Modern Tribe)", "url": "https://vilaswi.com/events/?eventDisplay=list", "kind": "modern_tribe"},
    {"name": "Boulder Junction (Modern Tribe)", "url": "https://boulderjct.org/events/?eventDisplay=list", "kind": "modern_tribe"},
    {"name": "Eagle River Chamber (Modern Tribe)", "url": "https://eagleriver.org/events/?eventDisplay=list", "kind": "modern_tribe"},
    {"name": "St. Germain Chamber (Micronet AJAX)", "url": "https://st-germain.com/events-calendar/?eventDisplay=list", "kind": "st_germain_ajax"},
    {"name": "Sayner–Star Lake–Cloverland Chamber (Modern Tribe)", "url": "https://sayner-starlake-cloverland.org/events/", "kind": "modern_tribe"},
    {"name": "Rhinelander Chamber (GrowthZone)", "url": "https://business.rhinelanderchamber.com/events/calendar", "kind": "growthzone"},
    {"name": "Minocqua Area Chamber (Simpleview)", "url": "https://www.minocqua.org/events/", "kind": "simpleview"},
    {"name": "Oneida County – Festivals & Events (Simpleview)", "url": "https://oneidacountywi.com/festivals-events/", "kind": "simpleview"},
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
        # Shim returns items and stashes debug so run_pipeline can log it
        def _shim(_html_text: str, base_url: str) -> List[Dict[str, Any]]:
            items, debug = st_germain_ajax(base_url, return_debug=True)  # type: ignore[assignment]
            _shim._last_debug = debug  # type: ignore[attr-defined]
            if items:
                return items
            # Fallback to Modern Tribe DOM parsing if AJAX gave nothing
            return parse_modern_tribe(_html_text, base_url=base_url)
        _shim._last_debug = {}  # type: ignore[attr-defined]
        return _shim
    raise ValueError(f"Unknown parser kind: {kind}")


# -------------------------------------------------------------------
# Pipeline
# -------------------------------------------------------------------
def run_pipeline(sources: List[Source]) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "when": now_iso(),
        "timezone": USER_TZ_NAME,
        "sources": [],
        "meta": {"status": "ok", "sources_file": "sources.yml"},
    }

    for src in sources:
        name, url, kind = src["name"], src["url"], src["kind"]
        row: Dict[str, Any] = {
            "name": name,
            "url": url,
            "fetched": 0,
            "parsed": 0,
            "added": 0,
            "samples": [],
            "http_status": None,
            "snapshot": f"state/snapshots/{_snapshot_name(name)}.html",
            "parser_kind": kind,  # show which parser ran
            "notes": {},          # place for AJAX/debug notes
        }

        try:
            parser_fn = _get_parser(kind)

            # Always fetch HTML (for snapshots + potential fallbacks)
            html, resp = fetch_url(url)
            row["http_status"] = resp.status_code
            row["fetched"] = 1
            save_snapshot(name, html)

            # Parse
            items: List[Dict[str, Any]] = parser_fn(html, base_url=url)  # type: ignore[misc]
            row["parsed"] = len(items)

            normalized = items
            row["added"] = len(normalized)

            # ---- JSON-safe samples (fix for datetime serialization) ----
            row["samples"] = [
                {
                    "title": _to_sample_field(n.get("title", "")),
                    "start": _to_sample_field(n.get("start", "")),
                    "location": _to_sample_field(n.get("location", "")),
                    "url": _to_sample_field(n.get("url", "")),
                }
                for n in normalized[:3]
            ]

            # capture AJAX debug notes if provided by shim
            notes = getattr(parser_fn, "_last_debug", None)  # type: ignore[attr-defined]
            if isinstance(notes, dict):
                # ensure notes are JSON-safe too
                row["notes"] = {k: _to_sample_field(v) for k, v in notes.items()}

        except Exception as e:
            row["error"] = repr(e)
            row["traceback"] = "".join(traceback.format_exception(type(e), e, e.__traceback__))

        report["sources"].append(row)

    return report


# -------------------------------------------------------------------
# Write report (always)
# -------------------------------------------------------------------
def _write_reports(report: Dict[str, Any]) -> List[str]:
    pretty = json.dumps(report, indent=2, ensure_ascii=False)

    out_a = os.path.join(REPO_ROOT, "last_run_report.json")
    out_b = os.path.join(REPO_ROOT, "state", "last_run_report.json")
    os.makedirs(os.path.dirname(out_b), exist_ok=True)

    with open(out_a, "w", encoding="utf-8") as f:
        f.write(pretty)
    with open(out_b, "w", encoding="utf-8") as f:
        f.write(pretty)

    return [out_a, out_b]


# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------
def main():
    report = {"meta": {"status": "ok"}}
    try:
        report = run_pipeline(SOURCES)
    except Exception as e:
        report = {
            "when": now_iso(),
            "timezone": USER_TZ_NAME,
            "sources": [],
            "meta": {"status": "error", "msg": str(e)},
        }
        report["meta"]["traceback"] = "".join(traceback.format_exception(type(e), e, e.__traceback__))

    paths = _write_reports(report)
    print("last_run_report.json written to:")
    for p in paths:
        print(" -", os.path.relpath(p, REPO_ROOT))

    total_parsed = sum(s.get("parsed", 0) for s in report.get("sources", []))
    total_added = sum(s.get("added", 0) for s in report.get("sources", []))
    print(f"Summary: parsed={total_parsed}, added={total_added}")


if __name__ == "__main__":
    main()
