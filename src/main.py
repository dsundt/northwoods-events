#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import json
import time
import yaml
import traceback
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional

import requests

# Parsers (these must exist as modules/files in src/parsers/)
# Each parser should expose one of:
#   parse(html: str) -> List[Dict]
#   or parse(url: str, html: str) -> List[Dict]
#   Items should contain: title, date_text or iso_hint/iso_end_hint, url, location (optional)
from parsers import modern_tribe, simpleview, growthzone
from normalize import parse_datetime_range, clean_text

STATE_DIR = "state"
SNAP_DIR = os.path.join(STATE_DIR, "snapshots")
REPORT_PATH = os.path.join(STATE_DIR, "last_run_report.json")
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --------------- utilities ---------------

def ensure_dirs() -> None:
    os.makedirs(SNAP_DIR, exist_ok=True)

def snap_name_from_source_name(name: str) -> str:
    safe = (
        name.lower()
        .replace(" ", "_")
        .replace("–", "-")
        .replace("—", "-")
        .replace("—", "-")
        .replace("&", "and")
        .replace("/", "_")
    )
    return f"{safe}.html"

def fetch_html(url: str, timeout: int = 30, max_attempts: int = 3) -> Tuple[Optional[str], Optional[int]]:
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }
    last_status = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            last_status = r.status_code
            if r.status_code == 200 and r.text and "<html" in r.text.lower():
                return r.text, r.status_code
            # 403 or HTML blockers will still come back as HTML;
            # we detect “non-HTML” by missing <html> tag.
        except Exception:
            last_status = None
        time.sleep(1.0)
    return None, last_status

def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

# --------------- sources ---------------

@dataclass
class Source:
    name: str
    url: str
    kind: str
    fetch_live: bool = True
    parser: Optional[str] = None  # explicit parser module key (optional)
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Defaults:
    tzname: str = "America/Chicago"
    default_duration_minutes: int = 120

def _first_existing(*paths: str) -> Optional[str]:
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None

def load_sources(path_arg: Optional[str]) -> Tuple[List[Source], Defaults]:
    """
    Look for sources in:
      - explicit path_arg if given
      - repo root: sources.yaml or sources.yml
      - src/:      sources.yaml or sources.yml
    """
    candidate = None
    if path_arg:
        candidate = _first_existing(path_arg)
    else:
        candidate = _first_existing("sources.yaml", "sources.yml", "src/sources.yaml", "src/sources.yml")

    if not candidate:
        raise FileNotFoundError("Could not find sources.yaml or sources.yml (root or src/).")

    with open(candidate, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    defaults_dict = data.get("defaults", {}) or {}
    defaults = Defaults(
        tzname=defaults_dict.get("tzname", "America/Chicago"),
        default_duration_minutes=int(defaults_dict.get("default_duration_minutes", 120)),
    )

    sources_list: List[Source] = []
    for obj in data.get("sources", []):
        sources_list.append(
            Source(
                name=obj["name"],
                url=obj["url"],
                kind=obj["kind"],
                fetch_live=bool(obj.get("fetch_live", True)),
                parser=obj.get("parser"),
                meta=obj.get("meta", {}) or {},
            )
        )
    return sources_list, defaults

# --------------- parser dispatcher ---------------

def run_parser(kind: str, url: str, html: str) -> List[Dict[str, Any]]:
    """
    Call into the appropriate parser module. We try flexible call signatures.
    """
    module = None
    if kind.lower() in ("modern_tribe", "tribe", "the-events-calendar"):
        module = modern_tribe
    elif kind.lower() in ("growthzone",):
        module = growthzone
    elif kind.lower() in ("simpleview", "simple_view"):
        module = simpleview
    else:
        raise ValueError(f"Unknown parser kind: {kind}")

    # Try parse(url, html) first, then parse(html)
    if hasattr(module, "parse"):
        fn = getattr(module, "parse")
        try:
            return fn(url, html)  # type: ignore[arg-type]
        except TypeError:
            return fn(html)       # type: ignore[arg-type]
    elif hasattr(module, "parse_html"):
        return module.parse_html(html)  # type: ignore[attr-defined]
    else:
        raise ValueError(f"Parser module for kind '{kind}' has no parse()")

# --------------- normalization ---------------

def normalize_rows(rows: List[Dict[str, Any]],
                   tzname: str,
                   default_duration_minutes: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        title = clean_text(row.get("title"))
        url = row.get("url") or ""
        location = clean_text(row.get("location"))
        date_text = clean_text(row.get("date_text"))
        iso_hint = clean_text(row.get("iso_hint"))
        iso_end_hint = clean_text(row.get("iso_end_hint"))

        start_dt, end_dt, all_day = parse_datetime_range(
            date_text=date_text,
            iso_hint=iso_hint or None,
            iso_end_hint=iso_end_hint or None,
            tzname=tzname,
        )
        if not end_dt and start_dt:
            end_dt = start_dt + timedelta(minutes=default_duration_minutes)

        out.append({
            "title": title,
            "url": url,
            "location": location,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "all_day": bool(all_day),
        })
    return out

# --------------- main runner ---------------

def main() -> None:
    ensure_dirs()

    # Allow optional CLI: python src/main.py [path-to-sources]
    sources_arg = sys.argv[1] if len(sys.argv) > 1 else None
    sources, defaults = load_sources(sources_arg)

    report = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "timezone": defaults.tzname,
        "sources": [],
    }

    all_events: List[Dict[str, Any]] = []

    for src in sources:
        entry = {
            "name": src.name,
            "url": src.url,
            "fetched": 0,
            "parsed": 0,
            "added": 0,
            "samples": [],
        }

        snap_name = snap_name_from_source_name(src.name)
        snap_path = os.path.join(SNAP_DIR, snap_name)

        html = None

        # 1) If we should fetch live (or if snapshot missing), fetch.
        must_fetch = src.fetch_live or (not os.path.isfile(snap_path))
        if must_fetch:
            fetched_html, status = fetch_html(src.url)
            if fetched_html:
                html = fetched_html
                write_text(snap_path, html)
                entry["fetched"] = 1
            else:
                # even if fetch fails, try to fall back to an existing snapshot
                if os.path.isfile(snap_path):
                    html = read_text(snap_path)
                else:
                    entry["error"] = "Live fetch failed and no snapshot HTML available"
                    report["sources"].append(entry)
                    continue
        else:
            # not forced to fetch — try reading snapshot; if empty, force a fetch
            html = read_text(snap_path)
            if not html:
                fetched_html, status = fetch_html(src.url)
                if fetched_html:
                    html = fetched_html
                    write_text(snap_path, html)
                    entry["fetched"] = 1
                else:
                    entry["error"] = "No snapshot HTML available"
                    report["sources"].append(entry)
                    continue

        # 2) Parse
        try:
            rows = run_parser(src.kind, src.url, html or "")
            entry["parsed"] = len(rows)
        except Exception as e:
            entry["error"] = f"Parser error: {e}"
            entry["traceback"] = traceback.format_exc()
            report["sources"].append(entry)
            continue

        # 3) Normalize
        try:
            normalized = normalize_rows(
                rows,
                tzname=defaults.tzname,
                default_duration_minutes=defaults.default_duration_minutes,
            )
            entry["added"] = len(normalized)
            entry["samples"] = normalized[:3]
            all_events.extend(normalized)
        except Exception as e:
            entry["error"] = f"Normalize error: {e}"
            entry["traceback"] = traceback.format_exc()

        report["sources"].append(entry)

    # 4) Write report + (optionally) ICS export
    try:
        write_text(REPORT_PATH, json.dumps(report, indent=2, ensure_ascii=False))
    except Exception:
        pass

    # Optional ICS writing: if you already have a function, call it here.
    # from calendar_out import write_ics
    # write_ics(all_events, "northwoods.ics")

    # Print a summary to logs
    total_added = sum(s.get("added", 0) for s in report["sources"])
    print(f"\nDone. Sources: {len(report['sources'])}, events added: {total_added}")
    print(f"Report: {REPORT_PATH}")
    if os.path.isfile(REPORT_PATH):
        with open(REPORT_PATH, "r", encoding="utf-8") as f:
            print(f.read()[:4000])

if __name__ == "__main__":
    main()
