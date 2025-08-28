#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Northwoods Events builder.
- Fetch -> Parse -> Normalize -> Write report (+ optional ICS)
- Always writes last_run_report.json, even if fatal errors occur.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# -------------------------------------------------------------------
# Ensure repo root and src/ are importable
# -------------------------------------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
for p in (REPO_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# -------------------------------------------------------------------
# Provide Event dataclass via stdlib types module
# (so parsers using "from types import Event" won't crash)
# -------------------------------------------------------------------
import types as _stdlib_types
try:
    from models import Event  # if you created src/models.py
except Exception:
    @dataclass
    class Event:
        title: str
        start: datetime
        end: Optional[datetime] = None
        location: str = ""
        url: str = ""
        all_day: bool = False

setattr(_stdlib_types, "Event", Event)

# -------------------------------------------------------------------
# Imports
# -------------------------------------------------------------------
try:
    from normalize import parse_datetime_range, clean_text
except Exception:
    from .normalize import parse_datetime_range, clean_text  # type: ignore


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _write_json(path: str, obj: Any) -> None:
    _ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def _snapshot_path(name: str) -> str:
    safe = (
        name.lower()
        .replace(" ", "_").replace("/", "_")
        .replace("–", "-").replace("—", "-")
        .replace("&", "and")
    )
    d = os.path.join(REPO_ROOT, "state", "snapshots")
    _ensure_dir(d)
    return os.path.join(d, f"{safe}.html")

def fetch_url(url: str, timeout: float = 30.0) -> Tuple[int, str]:
    import requests
    headers = {
        "User-Agent": "northwoods-events/1.0 (+github actions)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    return r.status_code, r.text

# -------------------------------------------------------------------
# Parser registry
# -------------------------------------------------------------------
def _get_parser(kind: str):
    k = (kind or "").strip().lower()
    if k in ("modern_tribe", "tribe", "the_events_calendar", "moderntribe"):
        from parsers.modern_tribe import parse_modern_tribe
        return parse_modern_tribe
    if k in ("growthzone", "gz"):
        from parsers.growthzone import parse_growthzone
        return parse_growthzone
    if k in ("simpleview", "simple_view", "sv"):
        from parsers.simpleview import parse_simpleview
        return parse_simpleview
    if k in ("municipal", "municipal_calendar", "muni", "calendar"):
        from parsers.municipal import parse_municipal
        return parse_municipal
    if k in ("ics", "ical", "icalendar"):
        from parsers.ics_feed import parse_ics
        return parse_ics
    raise ValueError(f"No parser available for kind='{kind}'")

# -------------------------------------------------------------------
# Sources loader
# -------------------------------------------------------------------
def load_sources(path_arg: Optional[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    import yaml
    candidates: List[str] = []
    if path_arg:
        candidates.append(path_arg)
    candidates += [
        os.path.join(REPO_ROOT, "sources.yaml"),
        os.path.join(REPO_ROOT, "sources.yml"),
        os.path.join(SRC_DIR, "sources.yaml"),
        os.path.join(SRC_DIR, "sources.yml"),
    ]
    chosen = next((p for p in candidates if os.path.isfile(p)), None)
    if not chosen:
        raise FileNotFoundError(f"Could not find sources.yaml/yml. Tried: {', '.join(candidates)}")
    with open(chosen, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return (data.get("sources", []) or [], data.get("defaults", {}) or {}, chosen)

# -------------------------------------------------------------------
# Pipeline
# -------------------------------------------------------------------
def run_pipeline(sources: List[Dict[str, Any]], defaults: Dict[str, Any]) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "when": _now_iso(),
        "timezone": os.environ.get("TZ") or "America/Chicago",
        "sources": [],
    }
    for src in sources:
        name = src.get("name", "(unnamed)")
        url = src.get("url")
        kind = src.get("kind") or defaults.get("kind") or ""
        row: Dict[str, Any] = {"name": name, "url": url, "fetched": 0, "parsed": 0, "added": 0, "samples": []}
        try:
            if not url:
                raise ValueError("Missing 'url'")
            status, text = fetch_url(url)
            row["fetched"] = 1
            row["http_status"] = status
            # snapshot
            spath = _snapshot_path(name)
            with open(spath, "w", encoding="utf-8") as f:
                f.write(text)
            row["snapshot"] = os.path.relpath(spath, REPO_ROOT)
            # parse
            parser_fn = _get_parser(kind)
            items: List[Dict[str, Any]] = parser_fn(text, base_url=url)  # type: ignore
            row["parsed"] = len(items)
            # normalize
            normalized: List[Dict[str, Any]] = []
            for it in items:
                title = clean_text(it.get("title"))
                location = clean_text(it.get("location", ""))
                href = it.get("url", "")
                iso = it.get("iso") or it.get("start_iso")
                iso_end = it.get("iso_end") or it.get("end_iso")
                date_text = it.get("date_text") or it.get("when") or ""
                start_dt, end_dt, all_day = parse_datetime_range(
                    date_text=date_text, iso_hint=iso, iso_end_hint=iso_end, tzname="America/Chicago"
                )
                normalized.append(
                    {
                        "title": title,
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat() if end_dt else None,
                        "all_day": all_day,
                        "location": location,
                        "url": href,
                    }
                )
            row["added"] = len(normalized)
            row["samples"] = [
                {"title": n["title"], "start": n["start"], "location": n.get("location", ""), "url": n.get("url", "")}
                for n in normalized[:3]
            ]
        except Exception as e:
            row["error"] = repr(e)
            row["traceback"] = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        report["sources"].append(row)
    return report

# -------------------------------------------------------------------
# Write report (always)
# -------------------------------------------------------------------
def _write_reports(report: Dict[str, Any]) -> List[str]:
    paths = []
    # repo root
    p1 = os.path.join(REPO_ROOT, "last_run_report.json")
    _write_json(p1, report)
    paths.append(p1)
    # state/
    _ensure_dir(os.path.join(REPO_ROOT, "state"))
    p2 = os.path.join(REPO_ROOT, "state", "last_run_report.json")
    _write_json(p2, report)
    paths.append(p2)
    return paths

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", help="Path to sources.yaml/yml (optional).", default=None)
    args = ap.parse_args(argv)

    report: Dict[str, Any] = {
        "when": _now_iso(),
        "timezone": os.environ.get("TZ") or "America/Chicago",
        "sources": [],
        "meta": {"status": "starting"},
    }

    try:
        sources, defaults, chosen_path = load_sources(args.sources)
        report["meta"] = {"status": "loaded", "sources_file": os.path.relpath(chosen_path, REPO_ROOT)}
        report = run_pipeline(sources, defaults)
        report["meta"] = {"status": "ok", "sources_file": os.path.relpath(chosen_path, REPO_ROOT)}
    except Exception as e:
        report["meta"] = {"status": "fatal_error", "error": repr(e)}
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
