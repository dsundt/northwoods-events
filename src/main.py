# src/main.py
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

# Local utilities (expect src/normalize.py present)
from normalize import parse_datetime_range, clean_text

# Parsers: import what exists, but keep optional to avoid hard-crash
# Each parser file should expose: parse(html: str) -> List[Dict[str, Any]]
PARSERS: Dict[str, Any] = {}
def _try_import():
    global PARSERS
    # Try common parser modules; ignore if missing so main still runs
    for key, modname in [
        ("modern_tribe", "parsers.modern_tribe"),
        ("growthzone", "parsers.growthzone"),
        ("simpleview", "parsers.simpleview"),
        ("municipal_calendar", "parsers.municipal_calendar"),
        ("ics", "parsers.ics"),  # if you have a dedicated ICS parser
    ]:
        try:
            mod = __import__(modname, fromlist=["*"])
            PARSERS[key] = mod
        except Exception:
            # not fatal; you'll just not be able to use that kind
            pass

_try_import()


# -----------------------------
# Config & I/O helpers
# -----------------------------

def find_sources_file(preferred: Optional[str]) -> str:
    """
    Resolve path to sources file. Accepts .yaml or .yml in repo root or src/.
    Search order:
      1) explicit user path if given
      2) ./sources.yaml
      3) ./sources.yml
      4) ./src/sources.yaml
      5) ./src/sources.yml
    """
    candidates: List[str] = []
    if preferred:
        candidates.append(preferred)
    candidates += [
        "sources.yaml",
        "sources.yml",
        os.path.join("src", "sources.yaml"),
        os.path.join("src", "sources.yml"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(
        f"Could not find sources file. Tried: {', '.join(candidates)}"
    )


def load_sources(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    defaults = data.get("defaults", {}) or {}
    sources = data.get("sources", []) or []
    # Materialize defaults into each source
    normalized_sources: List[Dict[str, Any]] = []
    for s in sources:
        merged = dict(defaults)
        merged.update(s or {})
        normalized_sources.append(merged)
    return normalized_sources, defaults


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\s\-\(\)&]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name.strip())
    return name.lower()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


# -----------------------------
# Networking / snapshot
# -----------------------------

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

def fetch_url(url: str, timeout: int = 30) -> Tuple[str, str, int, Dict[str, str]]:
    """
    Return (text, content_type, status_code, headers)
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    ctype = resp.headers.get("Content-Type", "").lower()
    return resp.text, ctype, resp.status_code, dict(resp.headers)


def save_snapshot(base: str, raw_html: str, rendered_html: Optional[str] = None) -> Dict[str, str]:
    """
    Save snapshots under state/snapshots/<base>.html and optional <base>.rendered.html.
    Returns mapping with keys 'snapshot' and optionally 'snapshot_rendered'.
    """
    ensure_dir("state/snapshots")
    out: Dict[str, str] = {}
    p1 = os.path.join("state", "snapshots", f"{base}.html")
    with open(p1, "w", encoding="utf-8") as f:
        f.write(raw_html)
    out["snapshot"] = p1
    if rendered_html:
        p2 = os.path.join("state", "snapshots", f"{base}.rendered.html")
        with open(p2, "w", encoding="utf-8") as f:
            f.write(rendered_html)
        out["snapshot_rendered"] = p2
    return out


# -----------------------------
# Parsing + normalization
# -----------------------------

def call_parser(kind: str, html: str, url: str) -> List[Dict[str, Any]]:
    """
    Call the appropriate parser by 'kind'.
    We always try to call with (html) first.
    If the parser supports (url, html), we will try that as a fallback.
    """
    k = kind.lower().strip()
    # aliasing
    if k in ("tribe", "the-events-calendar"):
        k = "modern_tribe"
    if k in ("simple_view",):
        k = "simpleview"

    mod = PARSERS.get(k)
    if not mod or not hasattr(mod, "parse"):
        raise ValueError(f"No parser available for kind='{kind}'")

    fn = getattr(mod, "parse")

    # preferred: parse(html)
    try:
        return fn(html)
    except TypeError:
        # fallback: parse(url, html)
        try:
            return fn(url, html)
        except TypeError:
            # last attempt: still try single-arg with html
            return fn(html)


def normalize_rows(
    rows: List[Dict[str, Any]],
    default_duration_minutes: int = 120,
) -> List[Dict[str, Any]]:
    """
    Rows can supply:
      - date_text (str)  human-readable range
      - iso_hint (str)   ISO start
      - iso_end_hint (str) ISO end
      - tzname (str)     optional tz like "America/Chicago"
      - title, url, location, etc.

    Returns rows with: start, end (ISO 8601), all_day (bool), plus cleaned text.
    """
    out: List[Dict[str, Any]] = []
    for r in rows:
        date_text = r.get("date_text") or ""
        iso_hint = r.get("iso_hint")
        iso_end_hint = r.get("iso_end_hint")
        tzname = r.get("tzname") or r.get("tz") or "America/Chicago"

        # compute datetimes
        try:
            start_dt, end_dt, all_day = parse_datetime_range(
                date_text=date_text,
                iso_hint=iso_hint,
                iso_end_hint=iso_end_hint,
                tzname=tzname,
            )
        except Exception:
            # very forgiving fallback: use ISO if present, else skip
            if iso_hint:
                try:
                    start_dt, end_dt, all_day = parse_datetime_range(
                        iso_hint=iso_hint,
                        iso_end_hint=iso_end_hint,
                        tzname=tzname,
                    )
                except Exception:
                    continue
            else:
                continue

        title = clean_text(r.get("title"))
        loc = clean_text(r.get("location"))

        out.append(
            {
                **r,
                "title": title,
                "location": loc,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "all_day": bool(all_day),
            }
        )
    return out


def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate by (title, start) tuple
    """
    seen = set()
    deduped = []
    for r in rows:
        key = (r.get("title"), r.get("start"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


# -----------------------------
# ICS writer (optional)
# -----------------------------

def write_ics(rows: List[Dict[str, Any]], path: str) -> None:
    """
    Minimal ICS writer to avoid adding more deps than needed.
    If you already use 'ics' lib elsewhere, feel free to swap this.
    """
    def esc(s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//northwoods-events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for i, r in enumerate(rows, 1):
        summary = esc(r.get("title", "Event"))
        location = esc(r.get("location", ""))
        url = esc(r.get("url", ""))
        uid = f"{abs(hash((summary, r.get('start'), r.get('end'), url))) }@northwoods"
        # Timestamps: use UTC "floating" (Z) form if they have offsets
        dtstart = r["start"].replace("-", "").replace(":", "")
        dtend = r["end"].replace("-", "").replace(":", "")
        # If they include offset (+/-), keep as-is (ics consumers usually handle)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"SUMMARY:{summary}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"LOCATION:{location}",
        ]
        if url:
            lines.append(f"URL:{url}")
        lines += ["END:VEVENT"]
    lines += ["END:VCALENDAR"]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines) + "\r\n")


# -----------------------------
# Reporting
# -----------------------------

@dataclass
class SourceReport:
    name: str
    url: str
    fetched: int = 0
    parsed: int = 0
    added: int = 0
    skipped_past: int = 0
    skipped_nodate: int = 0
    skipped_dupe: int = 0
    samples: List[Dict[str, Any]] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    rest_error: Optional[str] = None
    rest_fallback_unavailable: Optional[bool] = None
    http_status: Optional[int] = None
    snapshot: Optional[str] = None
    snapshot_rendered: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Prune Nones for a cleaner JSON
        return {k: v for k, v in d.items() if v not in (None, [], {})}


def write_last_run_report(timezone: str, reports: List[SourceReport]) -> None:
    ensure_dir("state")
    payload = {
        "when": datetime.now().isoformat(),
        "timezone": timezone,
        "sources": [r.to_dict() for r in reports],
    }
    with open(os.path.join("state", "last_run_report.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser(description="Northwoods events builder")
    parser.add_argument("--sources", default=None, help="Path to sources.(yaml|yml)")
    parser.add_argument("--out-ics", default="northwoods.ics", help="Where to write combined ICS")
    parser.add_argument("--default-duration", type=int, default=120, help="Default duration (min) when end is missing")
    parser.add_argument("--tz", default="America/Chicago", help="Display timezone label for report")
    args = parser.parse_args()

    sources_path = find_sources_file(args.sources)
    print(f"[main] Using sources file: {sources_path}")

    sources, _defaults = load_sources(sources_path)

    all_rows: List[Dict[str, Any]] = []
    reports: List[SourceReport] = []

    for src in sources:
        name = src.get("name") or src.get("title") or src.get("url") or "Unknown"
        url = src.get("url") or ""
        kind = (src.get("kind") or "").strip().lower()

        report = SourceReport(name=name, url=url, samples=[])
        print(f"\n[fetch] {name} [{kind}] - {url}")

        base_fn = sanitize_filename(name)
        try:
            text, ctype, status, headers = fetch_url(url)
            report.fetched = 1
            report.http_status = status

            # Save raw snapshot; for HTML always .html; for ICS that returned HTML, we’ll still write .html
            snaps = save_snapshot(base_fn, text)
            report.snapshot = snaps.get("snapshot")
        except Exception as e:
            report.error = repr(e)
            reports.append(report)
            print(f"[error] fetch failed: {e}")
            continue

        # If it's a calendar endpoint that returned HTML instead of ICS, note it (your ICS parser may rely on text/calendar)
        if "text/calendar" in ctype and kind not in ("ics",):
            # Some "ics" endpoints might be fed into modern_tribe/simpleview; handle as ICS explicitly if desired
            print("[warn] Received ICS content but parser kind is not 'ics'")

        try:
            rows_raw = call_parser(kind, text, url)
        except Exception as e:
            # Capture parser exceptions without killing the run
            report.error = repr(e)
            # Attach a short traceback-like message if available
            report.traceback = f"{type(e).__name__}: {e}"
            reports.append(report)
            print(f"[error] parser failed: {e}")
            continue

        report.parsed = len(rows_raw)

        # Normalize → start/end/all_day
        try:
            rows_norm = normalize_rows(rows_raw, default_duration_minutes=args.default_duration)
        except Exception as e:
            report.error = f"normalize_error: {repr(e)}"
            reports.append(report)
            print(f"[error] normalize failed: {e}")
            continue

        # Filter out ones without start/end
        good = [r for r in rows_norm if r.get("start") and r.get("end")]
        report.skipped_nodate = len(rows_norm) - len(good)

        # (Optional) filter past events — keep those starting today or later
        now_iso = datetime.now().isoformat()
        future = [r for r in good if r["end"] >= now_iso]
        report.skipped_past = len(good) - len(future)

        # Deduplicate
        final_rows = dedupe_rows(future)
        report.skipped_dupe = len(future) - len(final_rows)

        # Count + sample
        report.added = len(final_rows)
        report.samples = [
            {k: v for k, v in r.items() if k in ("title", "start", "location", "url")}
            for r in final_rows[:3]
        ]

        # Add to total
        all_rows.extend(final_rows)
        reports.append(report)

    # Write combined ICS (optional)
    try:
        if all_rows:
            write_ics(all_rows, args.out_ics)
            print(f"[ics] Wrote {len(all_rows)} events to {args.out_ics}")
        else:
            print("[ics] No events to write.")
    except Exception as e:
        print(f"[ics] Failed to write ICS: {e}")

    # Write last_run_report.json
    write_last_run_report(args.tz, reports)
    print("[report] state/last_run_report.json updated.")


if __name__ == "__main__":
    main()
