from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

# === Parsers ===
# Ensure these files exist in src/parsers/ with matching exported functions.
from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.municipal import parse_municipal
from parsers.st_germain_ajax import parse_st_germain_ajax

# === Date helpers ===
from utils.dates import looks_like_iso, try_parse_datetime_range

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------

STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "state")
SNAPSHOT_DIR = os.path.join(STATE_DIR, "snapshots")
REPORT_PATH = os.path.join(STATE_DIR, "last_run_report.json")

TIMEOUT = 30

ParserFn = Callable[[str, str], List[Dict[str, Any]]]

PARSERS: Dict[str, ParserFn] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
    "simpleview": parse_simpleview,
    "municipal": parse_municipal,
    "st_germain_ajax": parse_st_germain_ajax,
}

# ------------------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------------------

def _ensure_dirs() -> None:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

def _save_snapshot(name: str, html: str) -> str:
    # Keep filename format consistent with your run logs
    safe = name.lower().replace(" ", "_").replace("/", "_")
    path = os.path.join(SNAPSHOT_DIR, f"{safe}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path

def _fetch(url: str) -> requests.Response:
    headers = {
        "User-Agent": "northwoods-events-pipeline/1.0 (+https://example.org/bot)"
    }
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp

def _clean_text(s: str) -> str:
    return " ".join((s or "").split()).strip()

def _normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Final safety net:
      - drop items without a valid title or url
      - coerce start to ISO using the tolerant parser when possible
      - drop items whose 'start' cannot be normalized to a full date
    """
    out: List[Dict[str, Any]] = []
    for it in items:
        title = _clean_text(it.get("title", ""))
        url = _clean_text(it.get("url", ""))
        start = it.get("start")
        location = _clean_text(it.get("location", ""))

        if not title or not url:
            continue

        # If parser already produced ISO, accept
        if isinstance(start, str) and looks_like_iso(start):
            out.append({"title": title, "start": start, "url": url, "location": location})
            continue

        # Otherwise, try to parse any residual textual date
        start_iso = try_parse_datetime_range(_clean_text(str(start or "")))
        if start_iso:
            out.append({"title": title, "start": start_iso, "url": url, "location": location})
            continue

        # If still not parsable, skip (prevents "10:00 am" or nav copy from leaking)
        # You can alternatively default to an all-day 'today', but skipping is safer.
    return out

@dataclass
class Source:
    name: str
    url: str
    parser_kind: str

# ------------------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------------------

def run_pipeline(sources: List[Source]) -> Dict[str, Any]:
    _ensure_dirs()
    results: List[Dict[str, Any]] = []

    report = {
        "when": None,
        "timezone": "America/Chicago",
        "sources": [],
        "meta": {"status": "ok", "sources_file": "sources.yml"},
    }

    for src in sources:
        src_entry: Dict[str, Any] = {
            "name": src.name,
            "url": src.url,
            "fetched": 0,
            "parsed": 0,
            "added": 0,
            "samples": [],
            "http_status": None,
            "snapshot": None,
            "parser_kind": src.parser_kind,
            "notes": {},
            "error": None,
            "traceback": None,
        }

        try:
            parser_fn = PARSERS[src.parser_kind]
        except KeyError:
            src_entry["error"] = f"Unknown parser: {src.parser_kind}"
            report["sources"].append(src_entry)
            continue

        try:
            resp = _fetch(src.url)
            src_entry["fetched"] = 1
            src_entry["http_status"] = resp.status_code
            snapshot_path = _save_snapshot(
                f"{src.name} ({src.parser_kind})", resp.text
            )
            src_entry["snapshot"] = os.path.relpath(snapshot_path, os.path.join(os.path.dirname(__file__), ".."))

            # Parse
            raw_items = parser_fn(resp.text, base_url=src.url)
            # Normalize and filter
            items = _normalize_items(raw_items)

            src_entry["parsed"] = len(items)
            src_entry["added"] = len(items)
            src_entry["samples"] = items[:3]
            results.extend(items)

        except Exception as e:
            src_entry["error"] = repr(e)
            src_entry["traceback"] = traceback.format_exc()

        report["sources"].append(src_entry)

    # Timestamp (ISO with offset-free; caller/system can add tz if needed)
    from datetime import datetime as _dt
    report["when"] = _dt.now().isoformat()

    # Persist run report
    _ensure_dirs()
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return {"items": results, "report": report}

# ------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------

def _default_sources() -> List[Source]:
    # Mirror your current sources.yml (names matter only for snapshots/reports)
    return [
        Source("Vilas County (Modern Tribe)", "https://vilaswi.com/events/?eventDisplay=list", "modern_tribe"),
        Source("Boulder Junction (Modern Tribe)", "https://boulderjct.org/events/?eventDisplay=list", "modern_tribe"),
        Source("Eagle River Chamber (Modern Tribe)", "https://eagleriver.org/events/?eventDisplay=list", "modern_tribe"),
        Source("St. Germain Chamber (Micronet AJAX)", "https://st-germain.com/events-calendar/?eventDisplay=list", "st_germain_ajax"),
        Source("Sayner–Star Lake–Cloverland Chamber (Modern Tribe)", "https://sayner-starlake-cloverland.org/events/", "modern_tribe"),
        Source("Rhinelander Chamber (GrowthZone)", "https://business.rhinelanderchamber.com/events/calendar", "growthzone"),
        Source("Minocqua Area Chamber (Simpleview)", "https://www.minocqua.org/events/", "simpleview"),
        Source("Oneida County – Festivals & Events (Simpleview)", "https://oneidacountywi.com/festivals-events/", "simpleview"),
        Source("Town of Arbor Vitae (Municipal Calendar)", "https://www.townofarborvitae.org/calendar/", "municipal"),
    ]

if __name__ == "__main__":
    # If you want to supply a custom sources.yml loader, wire it here.
    sources = _default_sources()
    output = run_pipeline(sources)
    print(json.dumps(output["report"], indent=2))
