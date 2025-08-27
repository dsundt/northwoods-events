#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_DIR = os.path.join(ROOT, "state")
SNAP_DIR = os.path.join(STATE_DIR, "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)

CENTRAL_TZ = pytz.timezone("America/Chicago")
DEFAULT_UA = "northwoods-events/1.0 (+https://github.com/dsundt/northwoods-events)"

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def _now() -> str:
    return datetime.now(tz=CENTRAL_TZ).isoformat()

def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def fetch(url: str, timeout: int = 30) -> tuple[int, str]:
    headers = {"User-Agent": DEFAULT_UA}
    r = requests.get(url, headers=headers, timeout=timeout)
    return r.status_code, r.text

def clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s.strip())
    s = s.replace("\u200b", "").replace("\ufeff", "")
    return s

# --------------------------------------------------------------------
# Config resolution
# --------------------------------------------------------------------

def resolve_sources_path(cli_path: Optional[str]) -> str:
    """
    Look for sources.yml or sources.yaml gracefully.
    Order:
      1. --config if given and exists
      2. SOURCES_PATH env var if exists
      3. ./sources.yaml or ./sources.yml
      4. <repo-root>/sources.yaml or sources.yml
      5. ./src/sources.yaml or sources.yml
    """
    tried: List[str] = []

    def check(path: str) -> Optional[str]:
        if os.path.isfile(path):
            return path
        tried.append(path)
        return None

    # 1) CLI
    if cli_path and check(cli_path):
        return cli_path

    # 2) env
    env = os.environ.get("SOURCES_PATH")
    if env and check(env):
        return env

    # 3) cwd
    for fn in ("sources.yaml", "sources.yml"):
        p = os.path.join(os.getcwd(), fn)
        if check(p):
            return p

    # 4) repo root
    for fn in ("sources.yaml", "sources.yml"):
        p = os.path.join(ROOT, fn)
        if check(p):
            return p

    # 5) src/
    for fn in ("sources.yaml", "sources.yml"):
        p = os.path.join(ROOT, "src", fn)
        if check(p):
            return p

    raise FileNotFoundError(
        "Could not find sources.{yml,yaml}. Tried:\n  - " + "\n  - ".join(tried)
    )

# --------------------------------------------------------------------
# Load sources
# --------------------------------------------------------------------

@dataclass
class SourceCfg:
    name: str
    kind: str
    url: str
    tz: str
    ics_url: Optional[str] = None

def load_sources(path: str) -> Tuple[List[SourceCfg], Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    defaults = doc.get("defaults", {})
    out: List[SourceCfg] = []
    for s in doc.get("sources", []):
        out.append(SourceCfg(
            name=s["name"],
            kind=s["kind"],
            url=s["url"],
            tz=s.get("tz") or defaults.get("tz") or "America/Chicago",
            ics_url=s.get("ics_url"),
        ))
    return out, defaults

# --------------------------------------------------------------------
# Parsers (stubbed for brevity — fill with your existing implementations)
# --------------------------------------------------------------------

def parse_modern_tribe_html(html: str, name: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for a in soup.select("a.tribe-event-url, .tribe-events-calendar-list__event-title-link"):
        title = clean_text(a.get_text())
        href = a.get("href") or ""
        if not title or not href:
            continue
        rows.append({"title": title, "url": href, "source": name})
    return rows

# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main(argv: Optional[List[str]] = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="Path to sources.{yml,yaml}", default=None)
    args = ap.parse_args(argv)

    path = resolve_sources_path(args.config)
    print(f"[info] Using config: {path}")

    sources, defaults = load_sources(path)

    report = {
        "when": _now(),
        "timezone": "America/Chicago",
        "sources": [],
    }

    for src in sources:
        stats = {"name": src.name, "url": src.url}
        code, text = fetch(src.url)
        if code == 200:
            rows = parse_modern_tribe_html(text, src.name) if src.kind == "modern_tribe" else []
            stats["parsed"] = len(rows)
            stats["samples"] = rows[:2]
        else:
            stats["error"] = f"HTTP {code}"
        report["sources"].append(stats)

    out_path = os.path.join(STATE_DIR, "last_run_report.json")
    write_json(out_path, report)
    print(f"[done] wrote {out_path}")

if __name__ == "__main__":
    sys.exit(main())
