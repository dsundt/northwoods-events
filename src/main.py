from __future__ import annotations
import sys, json, os, logging
from dataclasses import dataclass
from typing import List, Dict, Any, Callable, Tuple
import requests

from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.municipal import parse_municipal
from parsers.st_germain_ajax import parse_st_germain_ajax

from utils.fetchers import fetch_text

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

ParserFn = Callable[[str, str], List[Dict[str, Any]]]

@dataclass
class Source:
    name: str
    url: str
    kind: str

PARSERS: Dict[str, ParserFn] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
    "simpleview": parse_simpleview,          # has internal JS-render fallback
    "municipal": parse_municipal,
    "st_germain_ajax": parse_st_germain_ajax # tries TEC JSON -> custom AJAX -> JS-render fallback
}

def _load_sources_from_stdin_or_yaml() -> List[Source]:
    # Prefer JSON from stdin if present
    data = None
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read().strip()
            if raw:
                data = json.loads(raw)
        except Exception:
            pass

    if data is None:
        # FALLBACK: sources.yml (if your pipeline uses YAML)
        yml = os.path.join(os.path.dirname(__file__), "..", "sources.yml")
        if os.path.exists(yml):
            try:
                import yaml  # requires PyYAML
                with open(yml, "r", encoding="utf-8") as f:
                    y = yaml.safe_load(f)
                entries = y.get("sources", [])
                return [Source(name=e["name"], url=e["url"], kind=e["kind"]) for e in entries]
            except Exception as e:
                logging.error("Failed to read sources.yml: %s", e)
                return []
        else:
            logging.error("No sources provided on stdin and no sources.yml found.")
            return []

    # JSON format: [{ name, url, kind }, ...]
    entries = []
    for e in data:
        entries.append(Source(name=e["name"], url=e["url"], kind=e["kind"]))
    return entries

def _fetch(url: str) -> Tuple[int, str]:
    try:
        return fetch_text(url)
    except requests.RequestException as e:
        logging.error("Fetch failed for %s: %s", url, e)
        return 0, ""

def main() -> None:
    sources = _load_sources_from_stdin_or_yaml()
    report: Dict[str, Any] = {
        "when": os.environ.get("NW_NOW") or "",
        "timezone": os.environ.get("NW_TZ") or "",
        "sources": [],
        "meta": {"status": "ok", "sources_file": "sources.yml"}
    }

    for s in sources:
        row: Dict[str, Any] = {
            "name": s.name, "url": s.url, "parser_kind": s.kind,
            "fetched": 0, "parsed": 0, "added": 0,
            "samples": [], "http_status": None, "snapshot": None,
            "notes": {}, "error": None, "traceback": None
        }
        parser_fn = PARSERS.get(s.kind)
        if not parser_fn:
            row["error"] = f"Unknown parser kind: {s.kind}"
            report["sources"].append(row)
            continue

        status, html = _fetch(s.url)
        row["http_status"] = status
        row["fetched"] = 1 if status == 200 else 0
        snap_dir = os.path.join(os.path.dirname(__file__), "..", "state", "snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        snap_name = f"{s.name.lower().replace(' ', '_').replace('—', '-').replace('–', '-')}__{s.kind}.html"
        snap_path = os.path.join(snap_dir, snap_name)
        try:
            with open(snap_path, "w", encoding="utf-8") as f:
                f.write(html or "")
            row["snapshot"] = os.path.relpath(snap_path, os.path.join(os.path.dirname(__file__), ".."))
        except Exception:
            pass

        items: List[Dict[str, Any]] = []
        if status == 200 and html:
            try:
                items = parser_fn(html, base_url=s.url)
            except Exception as e:
                row["error"] = repr(e)

        row["parsed"] = len(items)
        row["added"] = len(items)
        row["samples"] = items[:3]
        report["sources"].append(row)

    # Write reports
    out_pretty = os.path.join(os.path.dirname(__file__), "..", "last_run_report.json")
    out_state = os.path.join(os.path.dirname(__file__), "..", "state", "last_run_report.json")
    import json as _json, os as _os
    try:
        pretty = _json.dumps(report, ensure_ascii=False, indent=2)
        with open(out_pretty, "w", encoding="utf-8") as f:
            f.write(pretty)
        _os.makedirs(_os.path.dirname(out_state), exist_ok=True)
        with open(out_state, "w", encoding="utf-8") as f:
            f.write(pretty)
        print("== last_run_report.json (first 120 lines) ==")
        print(pretty.splitlines()[0:120])
    except Exception as e:
        logging.error("Failed to write report: %s", e)

if __name__ == "__main__":
    main()
