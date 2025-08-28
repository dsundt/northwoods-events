from __future__ import annotations
import json
import sys
from typing import Callable, Dict, List, Any
import requests

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

def fetch(url: str) -> requests.Response:
    headers = {
        "User-Agent": "northwoods-events/1.0 (+https://example.test)",
        "Accept": "text/html,application/xhtml+xml",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp

def run_source(name: str, url: str, kind: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "name": name, "url": url, "parser_kind": kind,
        "fetched": 0, "parsed": 0, "added": 0, "samples": [],
        "http_status": None, "notes": {}, "error": None, "traceback": None,
    }
    try:
        resp = fetch(url)
        out["http_status"] = resp.status_code
        out["fetched"] = 1
        parser_fn = PARSERS[kind]
        items = parser_fn(resp.text, base_url=url)
        out["parsed"] = len(items)
        out["added"] = len(items)
        out["samples"] = items[:3]
    except Exception as e:
        import traceback as _tb
        out["error"] = repr(e)
        out["traceback"] = _tb.format_exc()
    return out

def main():
    # Minimal runner: read sources.yml-like dict on stdin OR hardcode in your orchestrator
    # Expecting a list of {"name","url","parser_kind"}
    sources = json.load(sys.stdin)
    results = []
    for s in sources:
        results.append(run_source(s["name"], s["url"], s["parser_kind"]))
    print(json.dumps({"sources": results}, indent=2))

if __name__ == "__main__":
    main()
