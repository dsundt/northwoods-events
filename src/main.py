# -*- coding: utf-8 -*-
"""
Main runner:
- Reads sources from stdin (YAML).
- Fetches HTML (requests or Playwright for JS-heavy kinds).
- Calls appropriate parser function.
- Writes snapshots + state/last_run_report.json + state/events.json
"""

import sys
import os
import json
import time
import traceback
import io
from typing import List, Dict
from urllib.parse import urlparse

import yaml
from bs4 import BeautifulSoup  # ensure available; some parsers use it

from .resolve_sources import get_parser
from .fetch import fetch

STATE_DIR = "state"
SNAP_DIR = os.path.join(STATE_DIR, "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

JS_KINDS = {"simpleview", "st_germain_ajax"}  # use Playwright for these by default

def _slug(s: str) -> str:
    import re
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "page"

def _snapshot_name(name: str, kind: str) -> str:
    return f"{_slug(name)}__{kind}.html"

def main():
    raw = sys.stdin.read()
    cfg = yaml.safe_load(io.StringIO(raw)) or {}
    sources = cfg if isinstance(cfg, list) else cfg.get("sources", [])

    results: List[Dict] = []
    all_items: List[Dict] = []

    for s in sources:
        name = s.get("name") or s.get("title") or s.get("url")
        url = s.get("url")
        kind = s.get("parser") or s.get("parser_kind") or ""
        if not url or not kind:
            continue

        parser_fn = get_parser(kind)
        use_js = kind in JS_KINDS or os.getenv("USE_PLAYWRIGHT") == "1"

        # Optional selector hints per kind
        wait_selector = None
        if kind == "simpleview":
            wait_selector = 'a[href*="/event/"]'
        elif kind == "st_germain_ajax":
            wait_selector = 'a[href*="/events/"], a[href*="/events-calendar/"]'

        http_status, html = fetch(url, use_js=use_js, wait_selector=wait_selector, timeout=45)

        snap_path = os.path.join(SNAP_DIR, _snapshot_name(name, kind))
        try:
            # Store snapshot either way (even if a render error string)
            with open(snap_path, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

        parsed = 0
        added = 0
        samples: List[Dict] = []
        error = None
        tb = None
        items: List[Dict] = []

        if isinstance(html, str) and html.startswith("__RENDER_ERROR__"):
            error = html
        else:
            try:
                items = parser_fn(html, base_url=url)  # all parse_* fns accept (html, base_url=)
                parsed = len(items)
                added = len(items)  # you can apply your dedupe/store here if different
                samples = items[:3]
                all_items.extend(items)
            except Exception as e:
                error = repr(e)
                tb = traceback.format_exc()

        results.append({
            "name": name,
            "url": url,
            "parser_kind": kind,
            "fetched": 1,
            "parsed": parsed,
            "added": added,
            "samples": samples,
            "http_status": http_status,
            "snapshot": snap_path,
            "notes": {},
            "error": error,
            "traceback": tb,
        })

    report = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "timezone": os.getenv("TZ", "UTC"),
        "sources": results,
        "meta": {"status": "ok", "sources_file": "sources.yml"},
    }

    with open(os.path.join(STATE_DIR, "last_run_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # optional: write events.json (flat)
    with open(os.path.join(STATE_DIR, "events.json"), "w", encoding="utf-8") as f:
        json.dump(all_items, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
