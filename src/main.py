#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Northwoods Events builder: fetch -> parse -> normalize -> emit ICS + report.

This main.py is hardened to:
- avoid stdlib 'types' shadowing crashes
- make parsers that import "from types import Event" work (monkey-patch)
- make relative imports inside parser modules work even when run as a script
- find sources.yaml/yml in repo root or src/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 0) Ensure import paths are sane (repo root and src/)
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
for p in (REPO_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# 1) Provide an Event dataclass via the REAL stdlib `types` module
#    (so existing "from types import Event" in parsers continues to work).
# ---------------------------------------------------------------------------
import types as _stdlib_types  # real stdlib
try:
    # Prefer a dedicated local model if you already have one
    from models import Event  # type: ignore
except Exception:
    # Lightweight fallback so parsers never crash on Event import
    from dataclasses import dataclass
    from typing import Optional

    @dataclass
    class Event:  # type: ignore
        title: str
        start: datetime
        end: Optional[datetime] = None
        location: str = ""
        url: str = ""
        all_day: bool = False

# monkey-patch the stdlib `types` module to expose Event
# (safe: we only add a new attribute; we don’t replace existing ones)
setattr(_stdlib_types, "Event", Event)

# ---------------------------------------------------------------------------
# 2) Now we can safely import normalize and parser registry
# ---------------------------------------------------------------------------
try:
    from normalize import parse_datetime_range, clean_text  # noqa: F401
except Exception:
    # As a fallback, allow relative to work if running as a package
    from .normalize import parse_datetime_range, clean_text  # type: ignore  # noqa: F401

# Provide a tiny registry wrapper so main doesn’t depend on individual parsers.
def _get_parser(kind: str):
    """
    Dynamically map 'kind' -> parser function. We import lazily so import
    errors are localized to the specific kind.
    """
    k = (kind or "").strip().lower()
    if k in ("modern_tribe", "tribe", "the_events_calendar", "moderntribe"):
        try:
            try:
                from parsers.modern_tribe import parse_modern_tribe
            except Exception:
                # fallback if pkg relative import fails
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

# ---------------------------------------------------------------------------
# 3) Utilities
# ---------------------------------------------------------------------------
def load_sources(path_arg: Optional[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Read sources YAML. If path_arg is None, try:
      - sources.yaml, sources.yml, then src/sources.yaml, src/sources.yml
    Returns: (sources_list, defaults_dict)
    """
    import yaml  # pyyaml

    candidate_paths: List[str] = []
    if path_arg:
        candidate_paths.append(path_arg)
    candidate_paths += [
        os.path.join(REPO_ROOT, "sources.yaml"),
        os.path.join(REPO_ROOT, "sources.yml"),
        os.path.join(SRC_DIR, "sources.yaml"),
        os.path.join(SRC_DIR, "sources.yml"),
    ]

    chosen: Optional[str] = None
    for p in candidate_paths:
        if os.path.isfile(p):
            chosen = p
            break

    if not chosen:
        raise FileNotFoundError(
            f"Could not find sources.yaml/yml. Tried: {', '.join(candidate_paths)}"
        )

    with open(chosen, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    sources = data.get("sources", []) or []
    defaults = data.get("defaults", {}) or {}
    return sources, defaults


def fetch_url(url: str, timeout: float = 30.0) -> Tuple[int, str]:
    import requests

    headers = {
        "User-Agent": "northwoods-events/1.0 (+github actions)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    return r.status_code, r.text


def snapshot_path(name: str) -> str:
    safe = (
        name.lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("–", "-")
        .replace("—", "-")
        .replace("—", "-")
        .replace("&", "and")
    )
    d = os.path.join(REPO_ROOT, "state", "snapshots")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{safe}.html")


def write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 4) Main pipeline
# ---------------------------------------------------------------------------
def run_pipeline(sources: List[Dict[str, Any]], defaults: Dict[str, Any]) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "when": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "timezone": os.environ.get("TZ") or "America/Chicago",
        "sources": [],
    }

    total_added = 0

    for src in sources:
        name = src.get("name", "(unnamed)")
        url = src.get("url")
        kind = src.get("kind") or defaults.get("kind") or ""
        row: Dict[str, Any] = {
            "name": name,
            "url": url,
            "fetched": 0,
            "parsed": 0,
            "added": 0,
            "samples": [],
        }

        try:
            if not url:
                raise ValueError("Missing 'url'")

            # Fetch
            status, text = fetch_url(url)
            row["fetched"] = 1
            row["http_status"] = status

            # Snapshot
            snap = snapshot_path(name)
            with open(snap, "w", encoding="utf-8") as f:
                f.write(text)
            row["snapshot"] = os.path.relpath(snap, REPO_ROOT)

            # Parse
            parser_fn = _get_parser(kind)
            items: List[Dict[str, Any]] = parser_fn(text, base_url=url)  # type: ignore
            row["parsed"] = len(items)

            # Normalize (very light; assume parsers produce dicts)
            normalized: List[Dict[str, Any]] = []
            for it in items:
                title = clean_text(it.get("title"))
                location = clean_text(it.get("location", ""))
                href = it.get("url", "")

                # Expect either iso hints or human text; let normalize handle both
                iso = it.get("iso") or it.get("start_iso")
                iso_end = it.get("iso_end") or it.get("end_iso")
                date_text = it.get("date_text") or it.get("when") or ""

                start_dt, end_dt, all_day = parse_datetime_range(
                    date_text=date_text,
                    iso_hint=iso,
                    iso_end_hint=iso_end,
                    tzname="America/Chicago",
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
            total_added += len(normalized)

            # Stash a few samples for the report
            row["samples"] = [
                {
                    "title": n["title"],
                    "start": n["start"],
                    "location": n.get("location", ""),
                    "url": n.get("url", ""),
                }
                for n in normalized[:3]
            ]

            # Persist per-source JSON (optional)
            # with open(os.path.join(REPO_ROOT, "state", "latest.json"), "w", encoding="utf-8") as f:
            #     json.dump(normalized, f, indent=2, ensure_ascii=False)

        except Exception as e:
            row["error"] = repr(e)
            # Best-effort traceback for debugging
            try:
                import traceback as _tb

                row["traceback"] = "".join(_tb.format_exception(type(e), e, e.__traceback__))
            except Exception:
                pass

        report["sources"].append(row)

    # Write top-level report
    os.makedirs(os.path.join(REPO_ROOT, "state"), exist_ok=True)
    write_json(os.path.join(REPO_ROOT, "last_run_report.json"), report)

    # Optionally: write/merge ICS here if you have an ICS emitter;
    # we’ll keep it no-op to avoid colliding with your existing builder.
    return report


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Northwoods Events: build ICS and report")
    ap.add_argument(
        "--sources",
        help="Path to sources.yaml/yml. If omitted, search repo root then src/.",
        default=None,
    )
    args = ap.parse_args(argv)

    sources, defaults = load_sources(args.sources)
    report = run_pipeline(sources, defaults)

    # Print a tiny summary for logs
    total_parsed = sum(s.get("parsed", 0) for s in report["sources"])
    total_added = sum(s.get("added", 0) for s in report["sources"])
    print(f"Summary: parsed={total_parsed}, added={total_added}")
    # Non-fatal if 0 added; CI shouldn’t fail because of empty days.


if __name__ == "__main__":
    main()
