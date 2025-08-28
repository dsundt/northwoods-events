from __future__ import annotations
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import requests
import yaml

from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.municipal import parse_municipal
from parsers.st_germain_ajax import parse_st_germain_ajax

PARSERS: Dict[str, Callable[[str, str], List[Dict[str, Any]]]] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
    "simpleview": parse_simpleview,
    "municipal": parse_municipal,
    "st_germain_ajax": parse_st_germain_ajax,
}

DEFAULTS = {
    "tzname": "America/Chicago",
    "default_duration_minutes": 120,
}

@dataclass
class Source:
    name: str
    url: str
    kind: str

def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

def _load_sources() -> Tuple[List[Source], Dict[str, Any], str]:
    # 1) If stdin has JSON, read it (CI piping)
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read().strip()
            if raw:
                data = json.loads(raw)
                defaults = data.get("defaults") or DEFAULTS
                sources = [Source(**s) for s in data.get("sources") or []]
                return sources, defaults, "<stdin>"
        except Exception:
            pass

    # 2) YAML fallback (repo root or src/)
    for candidate in ("sources.yml", os.path.join(os.path.dirname(__file__), "sources.yml")):
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                y = yaml.safe_load(f) or {}
            defaults = y.get("defaults") or DEFAULTS
            sources = [Source(**s) for s in (y.get("sources") or [])]
            return sources, defaults, candidate

    print("No sources provided on stdin and no sources.yml found.", file=sys.stderr)
    return [], DEFAULTS, "<none>"

def _fetch(url: str) -> Tuple[int, str]:
    ua = "northwoods-events/1.0 (+github action)"
    headers = {"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"}
    r = requests.get(url, headers=headers, timeout=30)
    return r.status_code, r.text

def _snapshot_name(name: str, kind: str) -> str:
    safe = name.replace(" ", "_").replace("–", "-").replace("—", "-").replace("/", "_")
    safe = safe.replace("(", "").replace(")", "").replace("&", "and")
    return f"state/snapshots/{safe.lower()}_({kind}).html"

def main() -> None:
    sources, defaults, src_file = _load_sources()
    report_sources: List[Dict[str, Any]] = []
    os.makedirs("state/snapshots", exist_ok=True)

    for s in sources:
        row: Dict[str, Any] = {
            "name": s.name,
            "url": s.url,
            "fetched": 0, "parsed": 0, "added": 0,
            "samples": [],
            "http_status": None,
            "snapshot": _snapshot_name(s.name, s.kind),
            "parser_kind": s.kind,
            "notes": {},
            "error": None, "traceback": None,
        }
        try:
            status, html = _fetch(s.url)
            row["http_status"] = status
            with open(row["snapshot"], "w", encoding="utf-8") as f:
                f.write(html)
            row["fetched"] = 1

            parser_fn = PARSERS.get(s.kind)
            if not parser_fn:
                row["error"] = f"Unknown parser kind: {s.kind}"
            else:
                items = parser_fn(html, base_url=s.url)  # Some parsers may do extra HTTP (AJAX)
                row["parsed"] = len(items)
                row["added"] = len(items)
                row["samples"] = items[:3]

        except Exception as e:
            import traceback as tb
            row["error"] = repr(e)
            row["traceback"] = "".join(tb.format_exception(type(e), e, e.__traceback__))

        report_sources.append(row)

    report: Dict[str, Any] = {
        "when": _now_iso(),
        "timezone": DEFAULTS["tzname"],
        "sources": report_sources,
        "meta": {"status": "ok", "sources_file": os.path.basename(src_file)},
    }

    pretty = json.dumps(report, indent=2, ensure_ascii=False)
    with open("last_run_report.json", "w", encoding="utf-8") as f:
        f.write(pretty)
    os.makedirs("state", exist_ok=True)
    with open("state/last_run_report.json", "w", encoding="utf-8") as f:
        f.write(pretty)

    print("last_run_report.json written to:\n - last_run_report.json\n - state/last_run_report.json")
    print(f"Summary: parsed={sum(s['parsed'] for s in report_sources)}, added={sum(s['added'] for s in report_sources)}")

if __name__ == "__main__":
    main()
