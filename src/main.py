from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Iterable, Tuple

import yaml

# Local imports
from normalize import clean_text  # your existing file
# Parsers
from parsers import modern_tribe, simpleview, growthzone

PARSERS = {
    "modern_tribe": modern_tribe.parse,
    "growthzone": growthzone.parse,
    "simpleview": simpleview.parse,
    "ics": None,  # handled elsewhere in your project if you have an ICS ingestion
}

def _find_sources_path(user_arg: str | None) -> str:
    # 1) explicit
    if user_arg:
        return user_arg
    # 2) root: sources.yaml or sources.yml
    for p in ("sources.yaml", "sources.yml"):
        if Path(p).is_file():
            return p
    # 3) src/
    for p in ("src/sources.yaml", "src/sources.yml"):
        if Path(p).is_file():
            return p
    # 4) error
    raise FileNotFoundError("Could not find sources.yaml or sources.yml at repo root or in src/")

def load_sources(path: str) -> Tuple[list[dict], dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    defaults = data.get("_defaults", {})
    sources = data.get("sources", data if isinstance(data, list) else [])
    return sources, defaults

def read_snapshot(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def normalize_rows(rows: Iterable[Dict[str, Any]], default_duration_minutes: int | None = None) -> list[dict]:
    out = []
    seen = set()
    for r in rows:
        title = clean_text(r.get("title", ""))
        url = r.get("url", "")
        key = (title, url)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out

def write_report(report: Dict[str, Any], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", help="Path to sources.{yaml,yml}")
    args = ap.parse_args()

    sources_path = _find_sources_path(args.sources)
    sources, defaults = load_sources(sources_path)

    report = {"when": "", "timezone": "America/Chicago", "sources": []}

    added_total = 0
    for src in sources:
        name = src.get("name", "Unnamed")
        url = src["url"]
        kind = src.get("kind") or src.get("type") or "modern_tribe"
        parser = PARSERS.get(kind)

        entry = {"name": name, "url": url, "fetched": 0, "parsed": 0, "added": 0, "samples": []}

        try:
            # When running from snapshots, your pipeline likely provides
            # HTML in state/snapshots/<something>.html. Fall back to live URL if needed.
            snap = src.get("snapshot_path")
            html = None
            if snap and Path(snap).is_file():
                html = read_snapshot(snap)
                entry["fetched"] = 1
            elif url.startswith("http"):
                # If your original main fetched live HTML elsewhere, plug that in here.
                # To keep this drop-in simple, assume snapshots are used.
                pass

            if kind == "ics":
                # Leave as-is; your existing ICS ingestion can be called here if needed.
                rows = []
            else:
                if not html:
                    # No snapshot available; skip gracefully
                    entry["error"] = "No snapshot HTML available"
                    report["sources"].append(entry)
                    continue
                rows = list(parser(html, url))

            entry["parsed"] = len(rows)
            rows = normalize_rows(rows)
            entry["added"] = len(rows)
            entry["samples"] = rows[:3]
            added_total += entry["added"]
        except Exception as e:
            entry["error"] = repr(e)
        report["sources"].append(entry)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    write_report(report, Path("state/last_run_report.json"))

if __name__ == "__main__":
    main()
