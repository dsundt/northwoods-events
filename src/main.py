# src/main.py
from __future__ import annotations

import sys, json, os, io, datetime as dt
from typing import Any, Dict, List

# Support both "python -m src.main" and "python src/main.py"
try:
    from .resolve_sources import get_parser
    from .normalize import normalize
except ImportError:  # fallback when run as a script directly
    from resolve_sources import get_parser
    from normalize import normalize


def _read_sources_from_stdin_or_file() -> List[Dict[str, Any]]:
    """Read YAML piped in (preferred by CI), otherwise fall back to repo root sources.yml."""
    import yaml
    data: Dict[str, Any] = {}
    buf = sys.stdin.read()
    if buf.strip():
        data = yaml.safe_load(io.StringIO(buf)) or {}
    else:
        for cand in ("sources.yml", "sources.yaml"):
            if os.path.isfile(cand):
                data = yaml.safe_load(open(cand, "r", encoding="utf-8")) or {}
                break
    return data.get("sources", []) or []


def main() -> None:
    sources = _read_sources_from_stdin_or_file()

    all_events: List[Dict[str, Any]] = []
    per_source_report: List[Dict[str, Any]] = []

    print(f"Sources: {len(sources)}")
    for src in sources:
        if not isinstance(src, dict):
            continue
        if src.get("enabled") is False:
            continue

        name = src.get("name") or "(unnamed)"
        kind = (src.get("kind") or "").strip().lower()
        url = src.get("url")

        parser = get_parser(kind)
        parsed: List[Dict[str, Any]] = []
        try:
            parsed = parser(src) if parser else []
        except Exception as e:
            # Be resilient: a single bad source shouldn't break the whole run
            print(f"- {name} ({kind or 'unknown'}) ERROR: {e}")
            parsed = []

        added = normalize(parsed, source_name=name)
        print(f"- {name} ({kind or 'unknown'}) parsed: {len(parsed)} added: {len(added)}")

        all_events.extend(added)
        per_source_report.append({
            "name": name, "kind": kind or "unknown", "url": url,
            "parsed": len(parsed), "added": len(added)
        })

    # Ensure state dir
    os.makedirs("state", exist_ok=True)

    # Write events.json (array of normalized events)
    with open("state/events.json", "w", encoding="utf-8") as f:
        json.dump(all_events, f, ensure_ascii=False, indent=2)

    # Write last_run_report.json to help your diag page
    report = {
        "when": dt.datetime.utcnow().isoformat(timespec="microseconds") + "Z",
        "total_events": len(all_events),
        "per_source": per_source_report,
    }
    with open("state/last_run_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Optional: emit a summary line for logs
    print(f"Total normalized events: {len(all_events)}")


if __name__ == "__main__":
    main()
