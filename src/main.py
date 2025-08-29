# src/main.py
"""
Main entrypoint for scraping & report generation.

Tiny safety patch included:
- Skip non-dict list items in `sources` to prevent `'str'.get` crashes.
- Tolerant YAML/JSON loader (top-level mapping with `sources` or a bare list).
- Defensive per-source execution so one bad source can't kill the run.

Run as a module:
    python -m src.main < .tmp.sources.yaml
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from typing import Any, Dict, Iterable, List, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # YAML may not be needed if only JSON is used

# Prefer to use the repo's resolver; fall back gracefully if import ever fails.
try:
    from .resolve_sources import get_parser  # type: ignore
except Exception:  # pragma: no cover
    def get_parser(kind: str):
        return None


STATE_DIR = "state"
REPORT_PATH = os.path.join(STATE_DIR, "last_run_report.json")


def _load_sources_from_stdin() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Load YAML or JSON from stdin.
    Accepts:
      - mapping with 'sources' key (and optional 'defaults')
      - or a bare list of source mappings.
    Returns: (sources, defaults)
    """
    raw = sys.stdin.read()
    defaults: Dict[str, Any] = {}

    if not raw.strip():
        return [], defaults

    data: Any
    # Try YAML first (most common for this project), then JSON.
    if yaml is not None:
        try:
            data = yaml.safe_load(raw)
        except Exception:
            # Fall back to JSON if YAML parse fails.
            data = json.loads(raw)
    else:
        data = json.loads(raw)

    # Normalize into sources list + defaults dict
    if isinstance(data, dict):
        defaults = dict(data.get("defaults") or {})
        src = data.get("sources")
        if isinstance(src, list):
            sources = src
        elif isinstance(src, dict):
            # Rare shape: single mapping under 'sources'
            sources = [src]
        else:
            # No 'sources' key; try interpreting top-level dict as a single source
            sources = [data]
    elif isinstance(data, list):
        sources = data
    else:
        sources = []

    # Safety filter: keep only dict items (prevents `'str'.get` crash forever).
    sources = [s for s in sources if isinstance(s, dict)]

    return sources, defaults


def _safe_name(source: Dict[str, Any]) -> str:
    return (
        str(source.get("name"))
        or str(source.get("title") or "")
        or str(source.get("url") or "")
        or "Source"
    )


def _ensure_dirs() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(os.path.join(STATE_DIR, "snapshots"), exist_ok=True)


def main() -> int:
    start_ts = time.time()
    _ensure_dirs()

    sources, defaults = _load_sources_from_stdin()

    report_sources: List[Dict[str, Any]] = []
    total_parsed = 0
    total_added = 0
    total_errors = 0

    for idx, s in enumerate(sources):
        # Extra runtime guard (even though we filtered already).
        if not isinstance(s, dict):
            # Skip silently but record a minimal line for troubleshooting.
            report_sources.append(
                {"name": f"Item {idx}", "parsed": 0, "added": 0, "error": "non-dict"}
            )
            total_errors += 1
            continue

        name = _safe_name(s)
        kind = str(s.get("kind") or "").strip()
        url = str(s.get("url") or "").strip()

        parsed_count = 0
        added_count = 0
        error_msg = ""

        try:
            parser = get_parser(kind) if kind else None
            if parser is None:
                # No parser available for this kind; record as zero parsed.
                error_msg = f"no parser for kind '{kind}'"
            else:
                # Call the parser. Different parsers may return different shapes.
                # Be tolerant:
                result = parser(s, defaults)  # type: ignore[arg-type]

                # Interpret result in a few common shapes:
                if isinstance(result, dict):
                    # Prefer explicit fields if present
                    parsed_count = int(result.get("parsed", 0) or 0)
                    added_count = int(result.get("added", 0) or 0)
                    # If events list exists but parsed not provided, infer length
                    if parsed_count == 0 and isinstance(result.get("events"), list):
                        parsed_count = len(result["events"])
                        # If 'added' unspecified, assume equals parsed for report
                        if added_count == 0:
                            added_count = parsed_count
                elif isinstance(result, (list, tuple, set)):
                    parsed_count = len(result)  # list of events
                    added_count = parsed_count
                elif result is None:
                    # treat as no-op, keep zeros
                    pass
                else:
                    # Unknown type; count as zero with note
                    error_msg = f"unexpected parser return type: {type(result).__name__}"

        except Exception as e:  # never let a single source kill the run
            error_msg = f"{e.__class__.__name__}: {e}"

        # Update aggregates
        total_parsed += parsed_count
        total_added += added_count
        if error_msg:
            total_errors += 1

        # Record per-source in report
        entry = {
            "name": name,
            "kind": kind,
            "url": url,
            "parsed": parsed_count,
            "added": added_count,
        }
        if error_msg:
            entry["error"] = error_msg
            # Also print to stderr for easy log-grepping in CI
            print(f"[WARN] {name}: {error_msg}", file=sys.stderr)

        report_sources.append(entry)

    # Build final report
    finished_ts = time.time()
    report: Dict[str, Any] = {
        "started_at": start_ts,
        "finished_at": finished_ts,
        "duration_seconds": round(finished_ts - start_ts, 3),
        "sources": report_sources,
        "totals": {"parsed": total_parsed, "added": total_added, "errors": total_errors},
    }

    # Write report
    try:
        with io.open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"SUCCESS: last_run_report.json updated ({REPORT_PATH})")
    except Exception as e:
        # If writing to state fails, still return success code 0 to let the
        # workflow fall back to repo-root report if configured to do so.
        print(f"[ERROR] Failed to write report: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
