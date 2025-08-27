#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------- Path hygiene ----------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
for p in (REPO_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------- Make stdlib `types` export Event ----------
import types as _stdlib_types  # real stdlib
try:
    from models import Event  # if you have it
except Exception:
    from dataclasses import dataclass
    from typing import Optional as _Optional
    @dataclass
    class Event:  # minimal schema
        title: str
        start: datetime
        end: _Optional[datetime] = None
        location: str = ""
        url: str = ""
        all_day: bool = False
setattr(_stdlib_types, "Event", Event)

# ---------- Import normalize (tolerant) ----------
try:
    from normalize import parse_datetime_range, clean_text  # type: ignore
except Exception:
    from .normalize import parse_datetime_range, clean_text  # type: ignore

# ---------- Utils ----------
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

def _get_parser(kind: str):
    k = (kind or "").strip().lower()

    if k in ("modern_tribe", "tribe", "the_events_calendar", "moderntribe"):
        try:
            try:
                from parsers.modern_tribe import parse_modern_tribe
            except Exception:
                from modern_tribe import parse_modern_tribe  # type: ignore
            return parse_modern_tribe
        except Exception as e:
            raise ValueError(f"Modern Tribe parser load failed: {e}") from e

    if k in ("growthzone", "gz"):
        try:
            try:
                from parsers.growthzone import parse_growthzone
            except Exception:
                from growthzone import parse_growthzone  # type: ignore
            return parse_growthzone
        except Exception as e:
            raise ValueError(f"GrowthZone parser load failed: {e}") from e

    if k in ("simpleview", "simple_view", "sv"):
        try:
            try:
                from parsers.simpleview import parse_simpleview
            except Exception:
                from simpleview import parse_simpleview  # type: ignore
            return parse_simpleview
        except Exception as e:
            raise ValueError(f"Simpleview parser load failed: {e}") from e

    if k in ("municipal", "municipal_calendar", "muni", "calendar"):
        try:
            try:
                from parsers.municipal import parse_municipal
            except Exception:
                from municipal import parse_municipal  # type: ignore
            return parse_municipal
        except Exception as e:
            raise ValueError(f"Municipal parser load failed: {e}") from e

    if k in ("ics", "ical", "icalendar"):
        try:
            try:
                from parsers.ics_feed import parse_ics
            except Exception:
                from ics_feed import parse_ics  # type: ignore
            return parse_ics
        except Exception as e:
            raise ValueError(f"ICS parser load failed: {e}") from e

    raise ValueError(f"No parser available for kind='{kind}'")

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

# ---------- Pipeline ----------
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
            try:
                import traceback as _tb
                row["traceback"] = "".join(_tb.format_exception(type(e), e, e.__traceback__))
            except Exception:
                pass

        report["sources"].append(row)

    return report

# ---------- Main ----------
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

def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", help="Path to sources.yaml/yml (optional).", default=None)
    args = ap.parse_args(argv)

    # Build a minimal report up-front; expand as we succeed.
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
        # Fatal errors still produce a report
        report["meta"] = {"status": "fatal_error", "error": repr(e)}
        try:
            import traceback as _tb
            report["meta"]["traceback"] = "".join(_tb.format_exception(type(e), e, e.__traceback__))  # type: ignore
        except Exception:
            pass
    finally:
        paths = _write_reports(report)
        print("last_run_report.json written to:")
        for p in paths:
            print(" -", os.path.relpath(p, REPO_ROOT))

        # Small summary line
        total_parsed = sum(s.get("parsed", 0) for s in report.get("sources", []))
        total_added = sum(s.get("added", 0) for s in report.get("sources", []))
        print(f"Summary: parsed={total_parsed}, added={total_added}")

if __name__ == "__main__":
    main()
