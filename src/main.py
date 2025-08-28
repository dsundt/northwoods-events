# from __future__ must be first
from __future__ import annotations

import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests
import yaml

# Parsers
from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.municipal import parse_municipal
from parsers.st_germain_ajax import parse_st_germain_ajax


# ----------------------------
# Config & Utilities
# ----------------------------

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
STATE_DIR = ROOT / "state"
SNAPSHOT_DIR = STATE_DIR / "snapshots"
STATE_DIR.mkdir(exist_ok=True, parents=True)
SNAPSHOT_DIR.mkdir(exist_ok=True, parents=True)

DEFAULTS = {
    "tzname": "America/Chicago",
    "default_duration_minutes": 120,
}

PARSERS: Dict[str, Callable[[str, str], List[Dict[str, Any]]]] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
    "simpleview": parse_simpleview,
    "municipal": parse_municipal,
    "st_germain_ajax": parse_st_germain_ajax,
}


def _slug(name: str) -> str:
    s = name.lower()
    s = s.replace("–", "-")
    s = re.sub(r"[^a-z0-9 _\-\(\)\.]+", "_", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s


def _now_iso_with_tz() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _read_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _fetch(url: str, timeout: int = 30) -> requests.Response:
    headers = {
        "User-Agent": "northwoods-events-bot/1.0 (+https://example.com)",
        "Accept": "text/html,application/xhtml+xml",
    }
    return requests.get(url, headers=headers, timeout=timeout)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(text)


def _ensure_serializable(obj: Any) -> Any:
    """Recursively convert datetimes etc. into JSON-safe types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _ensure_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ensure_serializable(v) for v in obj]
    return obj


@dataclass
class SourceResult:
    name: str
    url: str
    fetched: int = 0
    parsed: int = 0
    added: int = 0
    samples: List[Dict[str, Any]] = None  # type: ignore
    http_status: Optional[int] = None
    snapshot: Optional[str] = None
    parser_kind: Optional[str] = None
    notes: Dict[str, Any] = None  # type: ignore
    error: Optional[str] = None
    traceback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["samples"] = d["samples"] or []
        d["notes"] = d["notes"] or {}
        return _ensure_serializable(d)


# ----------------------------
# Pipeline
# ----------------------------

def load_sources_from_yaml(path: Path) -> Dict[str, Any]:
    data = _read_yaml(path)
    cfg = dict(DEFAULTS)
    cfg.update(data.get("defaults", {}))
    cfg["sources"] = data.get("sources", [])
    return cfg


def run_pipeline(cfg: Dict[str, Any]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for src in cfg["sources"]:
        name: str = src["name"]
        url: str = src["url"]
        kind: str = src["kind"]
        parser_fn = PARSERS.get(kind)
        slug = _slug(name)
        result = SourceResult(name=name, url=url, samples=[], notes={}, parser_kind=kind)

        try:
            resp = _fetch(url)
            result.fetched = 1
            result.http_status = resp.status_code
            # Save snapshot (raw)
            snap_name = f"{slug}.html"
            snap_path = SNAPSHOT_DIR / snap_name
            _write_text(snap_path, resp.text)
            result.snapshot = str(snap_path.relative_to(ROOT)).replace("\\", "/")

            if not parser_fn:
                raise RuntimeError(f"No parser registered for kind={kind!r}")

            items = parser_fn(resp.text, base_url=url)
            result.parsed = len(items)
            result.added = len(items)
            result.samples = items[:3]

        except Exception as e:
            result.error = repr(e)
            result.traceback = "".join(traceback.format_exception(*sys.exc_info()))

        results.append(result.to_dict())

    report = {
        "when": _now_iso_with_tz(),
        "timezone": cfg.get("defaults", {}).get("tzname", DEFAULTS["tzname"])
        if "defaults" in cfg else cfg.get("tzname", DEFAULTS["tzname"]),
        "sources": results,
        "meta": {"status": "ok", "sources_file": "sources.yml"},
    }
    return report


def write_reports(report: Dict[str, Any]) -> List[str]:
    pretty = json.dumps(_ensure_serializable(report), indent=2, ensure_ascii=False)
    out1 = ROOT / "last_run_report.json"
    out2 = STATE_DIR / "last_run_report.json"
    _write_text(out1, pretty)
    _write_text(out2, pretty)
    return [str(out1), str(out2)]


def main() -> None:
    cfg = load_sources_from_yaml(ROOT / "sources.yml")
    report = run_pipeline(cfg)
    paths = write_reports(report)
    print("last_run_report.json written to:")
    for p in paths:
        print(f" - {p}")
    # summary
    total_parsed = sum(s.get("parsed", 0) for s in report["sources"])
    total_added = sum(s.get("added", 0) for s in report["sources"])
    print(f"Summary: parsed={total_parsed}, added={total_added}")


if __name__ == "__main__":
    main()
