from __future__ import annotations
import sys, io, os, json, time, traceback
import yaml
from bs4 import BeautifulSoup  # not strictly required but handy for future
from .resolve_sources import get_parser
from .fetch import fetch_html, should_use_playwright

STATE_DIR = "state"
SNAP_DIR = os.path.join(STATE_DIR, "snapshots")
REPORT_PATH = os.path.join(STATE_DIR, "last_run_report.json")

def _slug(name: str) -> str:
    s = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (name or "").strip())
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_") or "snapshot"

def _read_sources_from_stdin_or_file() -> list[dict]:
    data = sys.stdin.read()
    if data.strip():
        return yaml.safe_load(data) or []
    # fallback to local file (useful when not piping)
    if os.path.isfile("sources.yml"):
        return yaml.safe_load(io.open("sources.yml", "r", encoding="utf-8")) or []
    return []

def main() -> int:
    os.makedirs(SNAP_DIR, exist_ok=True)
    sources = _read_sources_from_stdin_or_file()
    out_sources = []
    total_parsed = 0
    total_added = 0

    for s in sources:
        name = s.get("name") or s.get("title") or s.get("url") or "Source"
        url = s.get("url", "").strip()
        kind = s.get("parser_kind") or s.get("kind") or ""
        wait_selector = s.get("wait_selector")  # optional override per source
        use_pw = should_use_playwright(kind, url)

        parsed = 0
        added = 0
        samples = []
        error = None
        snapshot_path = None
        http_status = None

        try:
            http_status, html = fetch_html(url, use_playwright=use_pw, wait_selector=wait_selector)
            # save snapshot
            snap_name = f"{_slug(name)}__{_slug(kind or 'unknown')}.html"
            snapshot_path = os.path.join(SNAP_DIR, snap_name)
            io.open(snapshot_path, "w", encoding="utf-8").write(html)

            parser_fn = get_parser(kind)
            if parser_fn is None:
                raise RuntimeError(f"No parser found for kind '{kind}'")

            events = parser_fn(html, url)
            # Normalize to a list of dicts with at least: title, start, url, location
            norm = []
            for ev in (events or []):
                if isinstance(ev, dict):
                    norm.append({
                        "title": ev.get("title", "").strip(),
                        "start": ev.get("start", "").strip() if ev.get("start") else "",
                        "url": ev.get("url", "").strip(),
                        "location": ev.get("location", "").strip() if ev.get("location") else "",
                    })
            parsed = len(norm)
            added = len(norm)
            samples = norm[:3]
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            # keep traceback in the snapshot folder for debugging
            tb_txt = traceback.format_exc()
            io.open(os.path.join(SNAP_DIR, f"{_slug(name)}__{_slug(kind)}.err.txt"), "w", encoding="utf-8").write(tb_txt)

        out_sources.append({
            "name": name,
            "url": url,
            "parser_kind": kind,
            "fetched": 1 if (http_status is not None or use_pw) else 0,
            "parsed": parsed,
            "added": added,
            "samples": samples,
            "http_status": http_status,
            "snapshot": snapshot_path.replace("\\", "/") if snapshot_path else "",
            "notes": {},
            "error": error,
            "traceback": None,
        })
        total_parsed += parsed
        total_added += added

    report = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "timezone": os.getenv("TZ", "UTC"),
        "sources": out_sources,
        "meta": {
            "status": "ok",
            "parsed_total": total_parsed,
            "added_total": total_added,
            "sources_file": "sources.yml",
        },
    }
    io.open(REPORT_PATH, "w", encoding="utf-8").write(json.dumps(report, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
