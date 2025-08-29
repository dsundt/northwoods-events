# src/main.py
from __future__ import annotations

import sys, io, os, json
from datetime import datetime

import yaml

from .resolve_sources import get_parser
from .state_store import load_events, save_events, merge_events, to_runtime_events
from .icsbuild import build_ics

STATE_DIR = "state"
SNAP_DIR = os.path.join(STATE_DIR, "snapshots")
REPORT_PATH = os.path.join(STATE_DIR, "last_run_report.json")

def _read_sources_from_stdin_or_file() -> tuple[list[dict], dict]:
    raw = sys.stdin.read()
    data = None
    if raw and raw.strip():
        try:
            data = yaml.safe_load(raw)
        except Exception:
            try:
                data = json.loads(raw)
            except Exception:
                data = None
    if data is None:
        try:
            with io.open("sources.yml", "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            data = None

    if data is None:
        return [], {}

    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict):
        sources = data.get("sources") or []
        defaults = data.get("defaults") or {}
        return (sources if isinstance(sources, list) else []), (defaults if isinstance(defaults, dict) else {})
    return [], {}

def _sanitize_source(src: dict, defaults: dict) -> dict:
    out = dict(src or {})
    for k, v in (defaults or {}).items():
        out.setdefault(k, v)
    if "wait_selector" not in out:
        wfs = out.get("wait_for_selectors")
        if isinstance(wfs, list) and wfs:
            out["wait_selector"] = ", ".join(str(x) for x in wfs if x)
    return out

def main() -> int:
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(SNAP_DIR, exist_ok=True)

    sources_raw, defaults = _read_sources_from_stdin_or_file()

    report_sources = []
    parsed_total = 0
    new_events_all: list[dict] = []

    for src in sources_raw:
        if not isinstance(src, dict):
            continue
        s = _sanitize_source(src, defaults)
        name = str(s.get("name") or "Unnamed")
        kind = str(s.get("kind") or "").strip().lower()
        url  = str(s.get("url") or "").strip()

        parsed = 0
        err = None

        def add_event(evt: dict):
            nonlocal parsed, new_events_all
            if isinstance(evt, dict):
                parsed += 1
                new_events_all.append(evt)

        try:
            parser = get_parser(kind) if kind else None
            if parser is None:
                err = f"no parser for kind '{kind}'"
            else:
                parser(s, add_event)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"

        report_sources.append({
            "name": name,
            "url": url,
            "parser_kind": kind,
            "parsed": parsed,
            "added": 0,  # filled after merge
            "error": err,
        })
        parsed_total += parsed

    # Merge into persistent store
    now = datetime.now().astimezone()
    store_path = os.path.join(STATE_DIR, "events.json")
    store = load_events(store_path)
    before_ct = len(store)
    store = merge_events(store, new_events_all, now)
    after_ct = len(store)
    save_events(store, store_path)
    delta = max(0, after_ct - before_ct)

    # Attribute adds approximately by parsed share
    total_weight = sum(max(1, s["parsed"]) for s in report_sources) or 1
    remaining = delta
    for i, rs in enumerate(report_sources):
        share = int(round(delta * (max(1, rs["parsed"]) / total_weight)))
        if i == len(report_sources) - 1:
            share = remaining
        rs["added"] = max(0, share)
        remaining -= share

    # Build ICS from the current store (best-effort)
    try:
        build_ics(to_runtime_events(store), "northwoods.ics")
    except Exception:
        pass

    report = {
        "when": now.isoformat(),
        "timezone": str(now.tzinfo),
        "sources": report_sources,
        "totals": {"parsed": parsed_total, "added": delta, "store_size": after_ct},
    }
    try:
        with io.open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Wrote report: {REPORT_PATH}")
        print(f"Sources: {len(report_sources)}")
        for s in report_sources[:10]:
            tail = f" ERR: {s['error']}" if s.get("error") else ""
            print(f"- {s['name']} parsed: {s['parsed']} added: {s['added']}{tail}")
    except Exception as e:
        print(f"[warn] could not write report: {e}", file=sys.stderr)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
