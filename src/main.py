# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
import time

import requests
from bs4 import BeautifulSoup

# Local imports
from normalize import parse_datetime_range, clean_text

# Parsers
from parsers import modern_tribe, simpleview, growthzone

DEFAULT_UA = "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0)"
ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__))) if os.path.basename(os.getcwd()) == "src" else os.path.abspath(os.getcwd())

@dataclass
class Source:
    name: str
    url: str
    kind: str

def _read_sources(path: Optional[str]) -> Tuple[List[Source], Dict[str, Any]]:
    # Find sources.{yaml,yml} defaulting to repo root, falling back to src/
    import yaml
    candidates = []
    if path:
        candidates = [path]
    else:
        candidates = [
            "sources.yaml", "sources.yml",
            os.path.join("src","sources.yaml"), os.path.join("src","sources.yml")
        ]
    chosen = None
    for p in candidates:
        if os.path.isfile(p):
            chosen = p
            break
    if not chosen:
        raise FileNotFoundError("Could not find sources.yaml/yml at repo root or src/")

    with open(chosen, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    defaults = cfg.get("defaults", {}) or {}
    lst = []
    for item in (cfg.get("sources") or []):
        lst.append(Source(
            name=item["name"],
            url=item["url"],
            kind=item.get("kind","modern_tribe"),
        ))
    return lst, defaults

def _fetch(url: str, timeout: int = 30) -> str:
    headers = {"User-Agent": DEFAULT_UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text

def _ensure_dirs():
    os.makedirs("state/snapshots", exist_ok=True)

def _snapshot_name(name: str) -> str:
    safe = name.lower().replace(" ", "_").replace("/", "_")
    safe = "".join(ch for ch in safe if ch.isalnum() or ch in "_.-()")
    return f"state/snapshots/{safe}.html"

def _parse(kind: str, html: str) -> List[Dict[str, Any]]:
    kind = (kind or "").lower().strip()
    if kind in ("modern_tribe","tec","the_events_calendar"):
        return modern_tribe.parse(html)
    if kind in ("simpleview","sv"):
        return simpleview.parse(html)
    if kind in ("growthzone","gz"):
        return growthzone.parse(html)
    # generic: try modern_tribe first
    rows = modern_tribe.parse(html)
    if rows:
        return rows
    return simpleview.parse(html)

def normalize_rows(rows: List[Dict[str, Any]], default_duration_minutes: int = 120) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        title = clean_text(r.get("title"))
        url = clean_text(r.get("url"))
        location = clean_text(r.get("location"))
        date_text = r.get("date_text") or ""
        iso_hint = r.get("iso_hint")
        iso_end_hint = r.get("iso_end_hint")

        start_dt, end_dt, all_day = parse_datetime_range(date_text=date_text, iso_hint=iso_hint, iso_end_hint=iso_end_hint)
        out.append({
            "title": title,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "all_day": all_day,
            "url": url,
            "location": location,
        })
    return out

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default=None, help="Optional explicit path to sources.yaml/yml")
    args = parser.parse_args()

    _ensure_dirs()
    run_report = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "timezone": "America/Chicago", "sources": []}

    sources, defaults = _read_sources(args.sources)

    for src in sources:
        entry = {"name": src.name, "url": src.url, "fetched": 0, "parsed": 0, "added": 0, "samples": []}
        snap_path = _snapshot_name(src.name)
        try:
            html = _fetch(src.url)
            entry["fetched"] = 1
            with open(snap_path, "w", encoding="utf-8") as f:
                f.write(html)

            rows = _parse(src.kind, html)
            entry["parsed"] = len(rows)

            if not rows:
                # Help diagnose: show first couple of <script type="application/ld+json"> lengths
                soup = BeautifulSoup(html, "lxml")
                ld = soup.find_all("script", attrs={"type": re.compile(r"^application/ld\+json$", re.I)})
                entry["debug"] = {
                    "ldjson_blocks": len(ld),
                    "first_title": (soup.title.get_text(strip=True) if soup.title else ""),
                }

            normalized = normalize_rows(rows)
            entry["added"] = len(normalized)
            entry["samples"] = [{"title": n["title"], "start": n["start"], "url": n["url"], "location": n["location"]} for n in normalized[:3]]

            # Append to a combined ICS later if you have that step; for now just write the run report.
        except Exception as e:
            entry["error"] = repr(e)
        finally:
            entry["snapshot"] = snap_path
            run_report["sources"].append(entry)

    os.makedirs("state", exist_ok=True)
    with open("state/last_run_report.json", "w", encoding="utf-8") as f:
        json.dump(run_report, f, indent=2)

if __name__ == "__main__":
    main()
