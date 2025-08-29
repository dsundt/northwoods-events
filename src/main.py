from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# Parsers
from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.municipal import parse_municipal
from parsers.st_germain_ajax import parse_st_germain_ajax

# ---- Config -----------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

PARSER_REGISTRY: Dict[str, Callable[..., List[Dict[str, Any]]]] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
    "simpleview": parse_simpleview,
    "municipal": parse_municipal,
    "st_germain_ajax": parse_st_germain_ajax,
}

STATE_DIR = "state"
SNAP_DIR = os.path.join(STATE_DIR, "snapshots")
REPORT_PATH = os.path.join(STATE_DIR, "last_run_report.json")


# ---- Helpers ----------------------------------------------------------------

def _ensure_dirs() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(SNAP_DIR, exist_ok=True)


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (s or "")).strip("_")[:120]


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
    }


def _fetch(url: str, timeout: int = 30) -> Tuple[int, str]:
    r = requests.get(url, headers=_headers(), timeout=timeout)
    return r.status_code, r.text


def _save_snapshot(name: str, parser_kind: str, html: str) -> str:
    fn = f"{_slug(name)}__{_slug(parser_kind)}.html"
    path = os.path.join(SNAP_DIR, fn)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def _load_sources() -> List[Dict[str, Any]]:
    # 1) sources.json
    if os.path.isfile("sources.json"):
        with open("sources.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("sources", [])

    # 2) sources.yml
    if os.path.isfile("sources.yml"):
        try:
            import yaml
        except Exception:
            print("WARN: pyyaml not installed; cannot read sources.yml", file=sys.stderr)
        else:
            with open("sources.yml", "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data if isinstance(data, list) else data.get("sources", [])

    # 3) optional stdin (for local/manual runs)
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                data = json.loads(raw)
                return data if isinstance(data, list) else data.get("sources", [])
    except Exception:
        pass

    print("WARN: No sources.json / sources.yml / stdin sources; continuing with empty list.", file=sys.stderr)
    return []


@dataclass
class SourceResult:
    name: str
    url: str
    parser_kind: str
    http_status: Optional[int] = None
    parsed: int = 0
    added: int = 0
    samples: List[Dict[str, Any]] = None
    snapshot: Optional[str] = None
    notes: Dict[str, Any] = None
    error: Optional[str] = None
    traceback: Optional[str] = None


# ---- Main run ---------------------------------------------------------------

def run_pipeline(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    _ensure_dirs()
    results: List[Dict[str, Any]] = []

    for s in sources:
        name = s.get("name", "")
        url = s.get("url", "")
        parser_kind = s.get("parser_kind") or s.get("parser") or ""
        notes: Dict[str, Any] = {}

        res = SourceResult(
            name=name,
            url=url,
            parser_kind=parser_kind,
            samples=[],
            notes=notes,
        )

        try:
            status, html = _fetch(url)
            res.http_status = status
            res.snapshot = _save_snapshot(name, parser_kind, html)

            parser_fn = PARSER_REGISTRY.get(parser_kind)
            if not parser_fn:
                raise ValueError(f"Unknown parser_kind: {parser_kind}")

            # Some parsers may need the base_url
            items = parser_fn(html, base_url=url)

            res.parsed = len(items)
            res.added = len(items)
            res.samples = items[:3]

        except Exception as e:
            res.error = repr(e)
            res.traceback = traceback.format_exc(limit=3)

        results.append({
            "name": res.name,
            "url": res.url,
            "parser_kind": res.parser_kind,
            "fetched": 1,
            "parsed": res.parsed,
            "added": res.added,
            "samples": res.samples or [],
            "http_status": res.http_status,
            "snapshot": res.snapshot,
            "notes": res.notes or {},
            "error": res.error,
            "traceback": res.traceback,
        })

    report = {
        "when": os.popen("date -u +\"%Y-%m-%dT%H:%M:%SZ\"").read().strip(),
        "timezone": "UTC",
        "sources": results,
        "meta": {"status": "ok", "sources_file": "sources.json" if os.path.isfile("sources.json") else "sources.yml"},
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Also mirror to repo root for convenience
    try:
        with open("last_run_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except Exception:
        pass

    return report


def main() -> None:
    sources = _load_sources()
    run_pipeline(sources)


if __name__ == "__main__":
    main()
