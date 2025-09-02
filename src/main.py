# src/main.py
"""
Main entrypoint (run as a module): `python -m src.main < .tmp.sources.yaml`

- No new parsing logic; only orchestrates the existing repo parsers.
- Keeps the output/paths your workflow expects:
    state/last_run_report.json
    state/events.json
    northwoods.ics
"""

from __future__ import annotations

import sys
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

import yaml

from .models import Event
from .resolve_sources import get_parser
from .icsbuild import build_ics


def _ensure_dirs() -> None:
    os.makedirs("state", exist_ok=True)
    os.makedirs("public", exist_ok=True)
    os.makedirs("public/state", exist_ok=True)
    os.makedirs("public/ics", exist_ok=True)


def _event_to_dict(e: Any) -> Dict[str, Any]:
    if is_dataclass(e):
        return asdict(e)
    if isinstance(e, dict):
        return e
    # As a last resort, try to convert a simple object with attributes
    return {
        "title": getattr(e, "title", None),
        "start": getattr(e, "start", None),
        "end": getattr(e, "end", None),
        "url": getattr(e, "url", None),
        "location": getattr(e, "location", None),
        "description": getattr(e, "description", None),
        "source": getattr(e, "source", None),
    }


def main() -> int:
    _ensure_dirs()

    # Read normalized sources (produced by .github/scripts/extract_sources.py)
    payload = yaml.safe_load(sys.stdin.read()) or {}
    sources = payload.get("sources", [])

    print(f"Sources: {len(sources)}")
    all_events: List[Dict[str, Any]] = []
    per_source = []

    def make_add_event(src_name: str):
        def _add(evt: Any):
            # Accept either dict or Event dataclass; normalize to dict
            d = _event_to_dict(evt)
            # Ensure source name retained for traceability if not provided
            d.setdefault("source", src_name)
            # Convert datetimes to isoformat strings (if not already)
            for k in ("start", "end"):
                v = d.get(k)
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            all_events.append(d)
        return _add

    for s in sources:
        name = s.get("name") or "(unnamed)"
        kind = s.get("kind") or ""
        url = s.get("url") or ""
        tzname = s.get("tzname")

        parser = get_parser(kind)
        parsed = added = 0

        if not parser:
            print(f"- {name} ({kind}) skipped: unknown kind '{kind}'")
            per_source.append({
                "name": name, "kind": kind, "url": url,
                "parsed": 0, "added": 0
            })
            continue

        add_event = make_add_event(name)

        try:
            # Each parser is expected to call add_event(...) for each item
            parsed = parser({"name": name, "kind": kind, "url": url, "tzname": tzname}, add_event)
            # If parser returns a count, use it; else approx with per-source additions
            if isinstance(parsed, int):
                # Items added in this iteration:
                added = len([e for e in all_events if e.get("source") == name]) - 0
            else:
                # Some parsers may not return a count; estimate from additions
                parsed = added = len([e for e in all_events if e.get("source") == name])
            print(f"- {name} ({kind}) parsed: {parsed} added: {added}")
        except Exception as ex:  # keep job alive, log error
            print(f"- {name} ({kind}) ERROR: {ex}")
            parsed = added = 0

        per_source.append({
            "name": name,
            "kind": kind,
            "url": url,
            "parsed": int(parsed),
            "added": int(added),
        })

    # Write state files
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "when": now,
        "total_events": len(all_events),
        "per_source": per_source,
    }
    with open("state/last_run_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Events file; your front-end already tolerates array or {"events":[...]}
    with open("state/events.json", "w", encoding="utf-8") as f:
        json.dump(all_events, f, ensure_ascii=False)

    # Build consolidated ICS (keep existing path)
    try:
        build_ics(all_events, "northwoods.ics")
    except Exception as ex:
        print(f"[warn] failed to build ICS: {ex}")

    print(f"Done. Wrote {len(all_events)} events.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
