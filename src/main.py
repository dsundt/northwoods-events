#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

from normalize import parse_datetime_range, clean_text
from parsers import get_parser

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)


# ---------------------------
# File helpers
# ---------------------------

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\s\-\(\)&]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name.strip())
    return name.lower()


def save_snapshot(base: str, html: str) -> str:
    ensure_dir("state/snapshots")
    path = os.path.join("state", "snapshots", f"{base}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


# ---------------------------
# Sources loader
# ---------------------------

def find_sources_file(explicit: Optional[str]) -> str:
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    candidates += [
        "sources.yaml",
        "sources.yml",
        os.path.join("src", "sources.yaml"),
        os.path.join("src", "sources.yml"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(f"Could not find sources file. Tried: {candidates}")


def load_sources(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    defaults = data.get("defaults", {}) or {}
    sources = data.get("sources", []) or []
    return sources, defaults


# ---------------------------
# Networking
# ---------------------------

def fetch_html(url: str, timeout: int = 30) -> Tuple[str, str, int]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    r = requests.get(url, headers=headers, timeout=timeout)
    return r.text, r.headers.get("Content-Type", ""), r.status_code


# ---------------------------
# Normalization
# ---------------------------

def normalize_events(rows: List[Dict[str, Any]],
                     default_duration_minutes: int = 120,
                     tzname: str = "America/Chicago") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        date_text = r.get("date_text") or ""
        iso_hint = r.get("iso_hint")
        iso_end_hint = r.get("iso_end_hint")

        try:
            start, end, all_day = parse_datetime_range(
                date_text=date_text,
                iso_hint=iso_hint,
                iso_end_hint=iso_end_hint,
                tzname=tzname,
            )
        except Exception:
            # If parsing fails for this row, skip it
            continue

        title = clean_text(r.get("title"))
        location = clean_text(r.get("location"))
        url = r.get("url", "")

        out.append({
            "title": title,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "all_day": bool(all_day),
            "url": url,
            "location": location,
        })
    return out


def dedupe(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for ev in events:
        key = (ev["title"], ev["start"])
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


# ---------------------------
# ICS writer
# ---------------------------

def write_ics(events: List[Dict[str, Any]], path: str) -> None:
    def esc(s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//northwoods-events//EN",
        "CALSCALE:GREGORIAN",
    ]
    for ev in events:
        uid = f"{abs(hash((ev['title'], ev['start'], ev['url'])))}@northwoods"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"SUMMARY:{esc(ev['title'])}",
            f"DTSTART:{ev['start'].replace('-','').replace(':','')}",
            f"DTEND:{ev['end'].replace('-','').replace(':','')}",
            f"LOCATION:{esc(ev['location'])}",
        ]
        if ev["url"]:
            lines.append(f"URL:{esc(ev['url'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines) + "\r\n")


# ---------------------------
# Runner
# ---------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", help="Path to sources.yaml/yml")
    ap.add_argument("--out-ics", default="northwoods.ics", help="Combined ICS output")
    args = ap.parse_args()

    sources_file = find_sources_file(args.sources)
    sources, defaults = load_sources(sources_file)

    reports: List[Dict[str, Any]] = []
    all_events: List[Dict[str, Any]] = []

    for src in sources:
        name = src.get("name", "Unknown")
        url = src["url"]
        kind = (src.get("kind") or "").lower()
        tzname = src.get("tzname", defaults.get("tzname", "America/Chicago"))
        dur = int(src.get("default_duration_minutes",
                          defaults.get("default_duration_minutes", 120)))

        base = sanitize_filename(name)
        report: Dict[str, Any] = {
            "name": name, "url": url, "fetched": 0, "parsed": 0, "added": 0
        }

        try:
            html, ctype, status = fetch_html(url)
            report["fetched"] = 1
            report["http_status"] = status
            report["snapshot"] = save_snapshot(base, html)

            parser_fn = get_parser(kind)  # will raise if kind unknown
            rows = parser_fn(html, url)   # parsers accept (html, base_url)
            report["parsed"] = len(rows)

            normalized = normalize_events(rows, dur, tzname)

            # filter out past events
            now_iso = datetime.now().isoformat()
            future = [ev for ev in normalized if ev["end"] >= now_iso]

            deduped = dedupe(future)
            report["added"] = len(deduped)
            report["samples"] = deduped[:3]

            all_events.extend(deduped)

        except Exception as e:
            report["error"] = f"{type(e).__name__}('{str(e)}')"
        reports.append(report)

    # Write ICS
    if all_events:
        write_ics(all_events, args.out_ics)

    # Write last_run_report.json
    ensure_dir("state")
    with open("state/last_run_report.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "when": datetime.now().isoformat(),
                "timezone": defaults.get("tzname", "America/Chicago"),
                "sources": reports,
            },
            f,
            indent=2,
        )


if __name__ == "__main__":
    main()
