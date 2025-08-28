from __future__ import annotations
import json, sys, os
from typing import Any, Dict, List, Callable
import requests

from parsers import (
    parse_modern_tribe,
    parse_growthzone,
    parse_simpleview,
    parse_st_germain_ajax,
    parse_municipal,
)

PARSERS: Dict[str, Callable[[str, str], List[Dict[str, Any]]]] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
    "simpleview": parse_simpleview,
    "st_germain_ajax": parse_st_germain_ajax,
    "municipal": parse_municipal,
}

def _read_sources_from_stdin_or_file() -> List[Dict[str, Any]]:
    buf = sys.stdin.read()
    if buf.strip():
        return json.loads(buf)
    # fallback: sources.json next to this script
    here = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(here, "sources.json")
    if os.path.exists(default_path):
        with open(default_path, "r", encoding="utf-8") as f:
            return json.load(f)
    raise SystemExit("No sources provided on stdin and no sources.json found.")

def run_pipeline(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    report = {"when": None, "timezone": None, "sources": [], "meta": {"status": "ok", "sources_file": "stdin"}}
    for src in sources:
        name = src["name"]; url = src["url"]; kind = src["parser_kind"]
        entry: Dict[str, Any] = {"name": name, "url": url, "parser_kind": kind}
        try:
            r = requests.get(url, timeout=30)
            entry["http_status"] = r.status_code
            entry["snapshot"] = src.get("snapshot", "")
            if r.ok:
                parser_fn = PARSERS[kind]
                items = parser_fn(r.text, base_url=url)
                entry["fetched"] = 1
                entry["parsed"] = len(items)
                entry["added"] = len(items)
                entry["samples"] = items[:3]
                entry["error"] = None
            else:
                entry["fetched"] = 0
                entry["parsed"] = 0
                entry["added"] = 0
                entry["samples"] = []
                entry["error"] = f"http {r.status_code}"
        except Exception as e:
            import traceback
            entry.setdefault("fetched", 1)
            entry["parsed"] = entry.get("parsed", 0)
            entry["added"] = entry.get("added", 0)
            entry["samples"] = entry.get("samples", [])
            entry["error"] = repr(e)
            entry["traceback"] = traceback.format_exc()
        report["sources"].append(entry)
    return report

def main() -> None:
    sources = _read_sources_from_stdin_or_file()
    report = run_pipeline(sources)
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
