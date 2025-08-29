# src/main.py
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime

import yaml

from .resolve_sources import get_parser
from .state_store import load_events, save_events, merge_events, to_runtime_events
from .icsbuild import build_ics

STATE_DIR = "state"
REPORT_PATH = os.path.join(STATE_DIR, "last_run_report.json")

def _read_sources_from_stdin_or_file():
    raw = sys.stdin.read()
    data = None
    if raw.strip():
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
        return (data.get("sources") or []), (data.get("defaults") or {})
    return [], {}

def _sanitize_source(src: dict, defaults: dict) -> dict:
    out = dict(src or {})
    for k, v in (defaults or {}).items():
        out.setdefault(k, v)
    # allow legacy wait_for_selectors
    if "wait_selector" not in out and isinstance(out.get("wait_for_selectors"), list):
        out["wait_selector"] = ", ".join(x for x in out["wait_for_selectors"] if x)
    return out

def main() -> int:
    os.makedirs(STATE_DIR, exist_ok=True)

    sources_raw, defaults = _read_sources_from_stdin_or_file()
    report_sources = []
    all_new = []
    total_parsed = 0

    for src in sources_raw:
        if not isinstance(src, dict):
            continue
        s = _sanitize_source(src, defaults)
        name = str(s.get("name") or "Unnamed")
        kind = str(s.get("kind") or "").strip().lower()
        parsed = 0
        err = None

        def add_event(e: dict):
            nonlocal parsed, all_new
            if isinstance(e, dict):
                parsed += 1
                all_new.append(e)

        try:
            parser = get_parser(kind)
            parser(s, add_event)
        except Exception as ex:
            err = f"{type(ex).__name__}: {ex}"

        total_parsed += parsed
        report_sources.append({
            "name": name,
            "url": s.get("url", ""),
            "parser_kind": kind,
            "parsed": parsed,
            "added": 0,  # filled after merge
            "error": err,
        })

    now = datetime.now().astimezone()
    store_path = os.path.join(STATE_DIR, "events.json")
    store = load_events(store_path)
    before = len(store)
    store = merge_events(store, all_new, now)
    after = len(store)
    save_events(store, store_path)
    delta = max(0, after - before)

    # attribute "added" roughly proportionally to parsed counts
    total_weight = sum(max(1, s["parsed"]) for s in report_sources) or 1
    rest = delta
    for i, rs in enumerate(report_sources):
        share = int(round(delta * (max(1, rs["parsed"]) / total_weight)))
        if i == len(report_sources) - 1:
            share = rest
        rs["added"] = max(0, share)
        rest -= share

    # Build ICS (best-effort)
    try:
        build_ics(to_runtime_events(store), "northwoods.ics")
    except Exception:
        pass

    report = {
        "when": now.isoformat(),
        "timezone": str(now.tzinfo),
        "sources": report_sources,
        "totals": {"parsed": total_parsed, "added": delta, "store_size": after},
    }
    with io.open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # console summary
    print(f"Sources: {len(report_sources)}")
    for s in report_sources[:10]:
        tail = f" ERR: {s['error']}" if s.get("error") else ""
        print(f"- {s['name']} parsed: {s['parsed']} added: {s['added']}{tail}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
