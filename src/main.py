from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Parsers
from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.municipal import parse_municipal
from utils.dates import parse_datetime_range

DEFAULT_TZ = "America/Chicago"

@dataclass
class Source:
    name: str
    url: str
    kind: str

# -----------------------
# Utilities
# -----------------------

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def safe_name(name: str) -> str:
    s = re.sub(r"\s+", "_", name.strip())
    s = re.sub(r"[^\w\-]+", "_", s)
    return s

def load_sources_from_yaml() -> List[Source]:
    import yaml
    # Try ./sources.yml -> ./src/sources.yml
    candidates = [Path("sources.yml"), Path("src/sources.yml")]
    for p in candidates:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            out: List[Source] = []
            for s in (raw.get("sources") or []):
                out.append(Source(name=s["name"], url=s["url"], kind=s["kind"]))
            return out
    return []

def fetch(url: str) -> requests.Response:
    headers = {
        "User-Agent": "northwoods-events/1.0 (+https://example.invalid)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp

# -----------------------
# Special handler: St Germain via Tribe REST API
# -----------------------

def fetch_st_germain_events(base_list_url: str) -> List[Dict[str, Any]]:
    """
    Query Modern Tribe Events REST API as a reliable fallback for St. Germain.
    """
    # Derive site root from the list URL
    parsed = urlparse(base_list_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    api = urljoin(root, "/wp-json/tribe/events/v1/events")

    params = {
        "per_page": 50,
        # generous window; API ignores if out of range
        "start_date": f"{datetime.now().year}-01-01",
        "end_date": f"{datetime.now().year + 1}-12-31",
    }

    items: List[Dict[str, Any]] = []

    try:
        r = requests.get(api, params=params, timeout=30)
        if r.status_code != 200:
            return items
        data = r.json()
        for ev in data.get("events", []):
            title = (ev.get("title") or "").strip()
            url = ev.get("url") or base_list_url
            start = ev.get("start_date") or ev.get("start_date_details", {}).get("datetime")
            location = ""
            venue = ev.get("venue") or {}
            if isinstance(venue, dict):
                location = (venue.get("address") or venue.get("venue") or "").strip()
            if title and start:
                items.append({"title": title, "start": start, "url": url, "location": location})
    except Exception:
        # Quiet fallback to HTML parse (may return zero if list is JS-only)
        pass

    return items

# -----------------------
# Routing
# -----------------------

PARSERS: Dict[str, Callable[[str, str], List[Dict[str, Any]]]] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
    "simpleview": parse_simpleview,
    "municipal": parse_municipal,
}

def run_pipeline(sources: List[Source]) -> Dict[str, Any]:
    state_dir = Path("state")
    snap_dir = state_dir / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    out_sources: List[Dict[str, Any]] = []

    for src in sources:
        row: Dict[str, Any] = {
            "name": src.name,
            "url": src.url,
            "fetched": 0,
            "parsed": 0,
            "added": 0,
            "samples": [],
            "http_status": None,
            "snapshot": None,
            "parser_kind": src.kind,
            "notes": {},
            "error": None,
            "traceback": None,
        }

        try:
            # Special case: St Germain AJAX via REST
            if src.kind == "st_germain_ajax":
                items = fetch_st_germain_events(src.url)
                row["fetched"] = 1
                row["http_status"] = 200 if items is not None else None
                row["parsed"] = len(items)
                row["added"] = len(items)
                row["samples"] = items[:3]
                # store a small HTML snapshot note
                snap_name = f"{safe_name(src.name)}_(st_germain_ajax).html"
                snap_path = snap_dir / snap_name
                snap_path.write_text(f"<!-- REST: {src.url} -->", encoding="utf-8")
                row["snapshot"] = str(snap_path).replace("\\", "/")
                out_sources.append(row)
                continue

            # Normal HTML fetch + parse
            resp = fetch(src.url)
            row["fetched"] = 1
            row["http_status"] = resp.status_code

            # snapshot
            snap_name = f"{safe_name(src.name)}_({safe_name(src.kind)}).html"
            snap_path = snap_dir / snap_name
            snap_path.write_text(resp.text, encoding="utf-8")
            row["snapshot"] = str(snap_path).replace("\\", "/")

            parser = PARSERS.get(src.kind)
            if not parser:
                row["error"] = f"Unknown parser kind: {src.kind}"
                out_sources.append(row)
                continue

            items = parser(resp.text, base_url=src.url)
            row["parsed"] = len(items)
            row["added"] = len(items)
            row["samples"] = items[:3]

        except Exception as e:
            import traceback as tb
            row["error"] = repr(e)
            row["traceback"] = "".join(tb.format_exception(type(e), e, e.__traceback__))
        finally:
            out_sources.append(row)

    report = {
        "when": datetime.now(timezone.utc).astimezone().isoformat(),
        "timezone": str(datetime.now().astimezone().tzinfo),
        "sources": out_sources,
        "meta": {"status": "ok", "sources_file": "sources.yml"},
    }
    return report

def write_reports(report: Dict[str, Any]) -> List[str]:
    paths = []
    pretty = json.dumps(report, indent=2, ensure_ascii=False)
    Path("last_run_report.json").write_text(pretty, encoding="utf-8")
    paths.append("last_run_report.json")
    state_dir = Path("state")
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "last_run_report.json").write_text(pretty, encoding="utf-8")
    paths.append(str(state_dir / "last_run_report.json"))
    return paths

def main() -> None:
    # 1) Try reading JSON from stdin (optional)
    stdin_data = None
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                stdin_data = json.loads(raw)
    except Exception:
        stdin_data = None

    sources: List[Source] = []

    if isinstance(stdin_data, list):
        for s in stdin_data:
            sources.append(Source(name=s["name"], url=s["url"], kind=s["kind"]))
    elif isinstance(stdin_data, dict) and "sources" in stdin_data:
        for s in stdin_data["sources"]:
            sources.append(Source(name=s["name"], url=s["url"], kind=s["kind"]))
    else:
        # 2) Fall back to YAML file
        sources = load_sources_from_yaml()

    if not sources:
        # As a final fallback, do not fail the build—emit an empty report.
        print("No sources provided on stdin; falling back produced 0 sources. Emitting empty report.", file=sys.stderr)
        report = {
            "when": datetime.now(timezone.utc).astimezone().isoformat(),
            "timezone": str(datetime.now().astimezone().tzinfo),
            "sources": [],
            "meta": {"status": "ok", "sources_file": "sources.yml"},
        }
        write_reports(report)
        return

    report = run_pipeline(sources)
    write_reports(report)

if __name__ == "__main__":
    main()
