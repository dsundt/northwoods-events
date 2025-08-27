#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
northwoods-events main runner

- Robust config resolution (sources.yml or sources.yaml; root or src/)
- Parsers: modern_tribe (HTML), modern_tribe_rest (REST), growthzone (HTML),
           municipal_calendar (HTML), ics
- Optional ICS fallback via `ics_url` in sources.yml when HTML/REST yields none
- Snapshots saved to state/snapshots/
- Cross-source dedupe
- Normalization via src/normalize.py (must be present)
- Outputs state/last_run_report.json with per-source stats & samples

CLI:
  python src/main.py                     # auto-discover config
  python src/main.py --config ./sources.yml
  SOURCES_PATH=./sources.yaml python src/main.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import pytz
import requests
import yaml
from bs4 import BeautifulSoup

# Normalization helper (we rely on your provided normalize.py)
# parse_datetime_range(date_text="...", iso_hint="...", iso_end_hint="...", tzname="...")
try:
    from normalize import parse_datetime_range, clean_text as norm_clean_text
except Exception:
    # Fallback no-op if normalize.py is missing; we won't crash, but dates won't normalize.
    def parse_datetime_range(*args, **kwargs):
        # naive: return now..now+2h, not all-day
        tz = pytz.timezone("America/Chicago")
        start = datetime.now(tz=tz)
        return start, start + timedelta(hours=2), False

    def norm_clean_text(s: Optional[str]) -> str:
        return (s or "").strip()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_DIR = os.path.join(ROOT, "state")
SNAP_DIR = os.path.join(STATE_DIR, "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)

CENTRAL_TZNAME = "America/Chicago"
CENTRAL_TZ = pytz.timezone(CENTRAL_TZNAME)
DEFAULT_UA = (
    "northwoods-events/1.0 (+https://github.com/dsundt/northwoods-events; "
    "contact: automation)"
)

# ------------------------------- Utils --------------------------------- #

def _now_iso() -> str:
    return datetime.now(tz=CENTRAL_TZ).isoformat()

def clean_text(s: Optional[str]) -> str:
    s = norm_clean_text(s)
    s = s.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", s).strip()

def sanitize_filename(name: str) -> str:
    name = name.lower()
    name = name.replace("–", "-").replace("—", "-").replace(" ", "_")
    name = re.sub(r"[^a-z0-9._\-]+", "", name)
    return name[:180]  # keep sane length

def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def fetch(url: str, timeout: int = 45) -> tuple[int, str, Dict[str, str]]:
    headers = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        return r.status_code, r.text, dict(r.headers or {})
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}", {}

def save_snapshot(name: str, body: str, suffix: str = ".html") -> str:
    path = os.path.join(SNAP_DIR, sanitize_filename(name) + suffix)
    write_text(path, body)
    return path

def resolve_sources_path(cli_path: Optional[str]) -> str:
    """Find sources.yml/yaml in common places, or honor CLI/env."""
    tried: List[str] = []

    def exists(p: str) -> Optional[str]:
        if os.path.isfile(p):
            return p
        tried.append(p)
        return None

    # CLI flag (exact path)
    if cli_path and exists(cli_path):
        return cli_path

    # Env
    env = os.environ.get("SOURCES_PATH")
    if env and exists(env):
        return env

    # CWD
    for fn in ("sources.yml", "sources.yaml"):
        p = os.path.join(os.getcwd(), fn)
        if exists(p):
            return p

    # Repo root
    for fn in ("sources.yml", "sources.yaml"):
        p = os.path.join(ROOT, fn)
        if exists(p):
            return p

    # src/
    for fn in ("sources.yml", "sources.yaml"):
        p = os.path.join(ROOT, "src", fn)
        if exists(p):
            return p

    raise FileNotFoundError("Could not locate sources.{yml,yaml}. Tried:\n  - " + "\n  - ".join(tried))

# ------------------------------- Models -------------------------------- #

@dataclass
class SourceCfg:
    name: str
    kind: str
    url: str
    tz: str
    ics_url: Optional[str] = None
    rest_window_days: int = 365  # for REST queries where applicable

@dataclass
class EventRow:
    title: str
    url: str
    date_text: str = ""
    iso_hint: str = ""
    iso_end_hint: str = ""
    location: str = ""
    source: str = ""
    tzname: str = CENTRAL_TZNAME

# ------------------------------- Loaders -------------------------------- #

def load_sources(path: str) -> Tuple[List[SourceCfg], Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    defaults = doc.get("defaults", {}) or {}
    tz_default = defaults.get("tz") or CENTRAL_TZNAME
    rest_window_days = int(defaults.get("rest_window_days", 365))

    out: List[SourceCfg] = []
    for s in doc.get("sources", []):
        out.append(
            SourceCfg(
                name=s["name"],
                kind=s["kind"],
                url=s["url"],
                tz=s.get("tz") or tz_default,
                ics_url=s.get("ics_url"),
                rest_window_days=int(s.get("rest_window_days", rest_window_days)),
            )
        )
    return out, defaults

# ------------------------------- Parsers -------------------------------- #

def parse_modern_tribe_html(html: str, base_url: str, src_name: str, tzname: str) -> List[EventRow]:
    """Very tolerant HTML scraper for The Events Calendar list views."""
    soup = BeautifulSoup(html, "lxml")
    rows: List[EventRow] = []

    # Try common selectors (V2 list, archive list, etc.)
    containers = soup.select(
        ".tribe-events-calendar-list__event, .tribe-common-g-row, article.type-tribe_events"
    )
    if not containers:
        # Fallback: just pick any anchors with event URLs in them
        anchors = soup.select("a.tribe-event-url, a.tribe-events-calendar-list__event-title-link, .tribe-event-url a, a.url")
        for a in anchors:
            title = clean_text(a.get_text())
            href = a.get("href") or ""
            if title and href:
                rows.append(EventRow(title=title, url=urljoin(base_url, href), source=src_name, tzname=tzname))
        return rows

    for el in containers:
        a = el.select_one("a.tribe-event-url, a.tribe-events-calendar-list__event-title-link, a.url")
        if not a:
            continue
        title = clean_text(a.get_text())
        href = urljoin(base_url, a.get("href") or "")
        if not title or not href:
            continue

        # Try to pick up ISO times or text dates
        iso_start = ""
        iso_end = ""
        date_text = ""

        # time[datetime] is often present
        t_start = el.select_one("time[datetime]")
        if t_start and t_start.has_attr("datetime"):
            iso_start = (t_start["datetime"] or "").strip()

        # Look for any end time/time[datetime]
        t_ends = el.select("time[datetime]")
        if len(t_ends) >= 2 and t_ends[1].has_attr("datetime"):
            iso_end = (t_ends[1]["datetime"] or "").strip()

        # Fallback: textual date range in badges or meta
        if not iso_start:
            txtbits = []
            for sel in [
                ".tribe-events-calendar-list__event-date-tag",
                ".tribe-events-calendar-list__event-datetime",
                ".tribe-event-date-start",
                ".tribe-event-date",
                ".tribe-common-b2",
                ".tribe-common-b3",
            ]:
                t = el.select_one(sel)
                if t:
                    txtbits.append(clean_text(t.get_text()))
            if txtbits:
                date_text = " – ".join([b for b in txtbits if b])

        # Location
        loc = ""
        loc_el = el.select_one(".tribe-events-venue, .tribe-events-calendar-list__event-venue, .tribe-events-calendar-list__event-venue-title")
        if loc_el:
            loc = clean_text(loc_el.get_text())

        rows.append(
            EventRow(
                title=title,
                url=href,
                date_text=date_text,
                iso_hint=iso_start,
                iso_end_hint=iso_end,
                location=loc,
                source=src_name,
                tzname=tzname,
            )
        )
    return rows

def parse_modern_tribe_rest(list_url: str, src_name: str, tzname: str, days: int) -> Tuple[List[EventRow], Optional[str]]:
    """
    Try the official REST endpoint:
      <site>/wp-json/tribe/events/v1/events?start_date=...&end_date=...
    Some sites disable it (404/403). Return rows + optional rest_error.
    """
    # Derive base: https://example.com/... -> https://example.com/
    parsed = urlparse(list_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    api = urljoin(base, "/wp-json/tribe/events/v1/events")

    # Window
    start = datetime.now(tz=pytz.UTC).isoformat()
    end = (datetime.now(tz=pytz.UTC) + timedelta(days=days)).isoformat()

    params = {"per_page": 100, "page": 1, "start_date": start, "end_date": end}
    headers = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}

    rows: List[EventRow] = []
    rest_error: Optional[str] = None
    try:
        r = requests.get(api, headers=headers, params=params, timeout=45)
        if r.status_code != 200:
            rest_error = f"HTTPError('{r.status_code} for {r.url}')"
            return rows, rest_error
        data = r.json()
        evs = data.get("events") or []
        for ev in evs:
            title = clean_text(ev.get("title") or "")
            url = ev.get("url") or ev.get("link") or ""
            start_iso = (ev.get("start_date") or ev.get("start_date_details", {}).get("date")) or ""
            end_iso = (ev.get("end_date") or ev.get("end_date_details", {}).get("date")) or ""
            venue = clean_text(
                (ev.get("venue") or {}).get("venue") or (ev.get("venue") or {}).get("address") or ""
            )
            if title and url:
                rows.append(
                    EventRow(
                        title=title,
                        url=url,
                        iso_hint=start_iso,
                        iso_end_hint=end_iso,
                        location=venue,
                        source=src_name,
                        tzname=tzname,
                    )
                )
        return rows, None
    except Exception as e:
        rest_error = f"{type(e).__name__}('{e}')"
        return rows, rest_error

def parse_growthzone_html(html: str, base_url: str, src_name: str, tzname: str) -> List[EventRow]:
    """
    Generic GrowthZone list scraper (best-effort).
    Looks for event tiles/rows and grabs title/url/date-ish text nearby.
    """
    soup = BeautifulSoup(html, "lxml")
    rows: List[EventRow] = []

    # Common GrowthZone selectors
    cards = soup.select(
        ".gz-event, .gzc-event, .event-item, .eventlist-item, "
        "li.event, .chambermaster-event, .listItem, .itemContainer"
    )
    anchors = soup.select('a[href*="/events/details/"], a[href*="/events/details"], a.event-title, .event-title a')
    if not cards and not anchors:
        # Fallback: grab any calendar links that look like details
        anchors = soup.select('a[href*="events/"], a.event-title, .event-title a')

    seen = set()
    def add_row(a, date_text_guess: str = ""):
        title = clean_text(a.get_text())
        href = urljoin(base_url, a.get("href") or "")
        key = (title.lower(), href)
        if title and href and key not in seen:
            seen.add(key)
            rows.append(EventRow(title=title, url=href, date_text=date_text_guess, source=src_name, tzname=tzname))

    # From anchors directly
    for a in anchors:
        # try to find a nearby date text
        date_guess = ""
        parent = a.find_parent()
        if parent:
            ctx = clean_text(parent.get_text())
            # keep it shortish
            if 0 < len(ctx) <= 240:
                date_guess = ctx
        add_row(a, date_guess)

    # From cards (if unique)
    for c in cards:
        a = c.select_one("a, .event-title a")
        if not a:
            continue
        date_guess = ""
        for sel in [
            ".date", ".event-date", ".gz-event-date", ".gz-event-time", ".details", ".content"
        ]:
            el = c.select_one(sel)
            if el:
                date_guess = clean_text(el.get_text())
                break
        add_row(a, date_guess)

    return rows

def parse_municipal_calendar_html(html: str, base_url: str, src_name: str, tzname: str) -> List[EventRow]:
    """
    Generic municipal calendar (table-style) scraper.
    Very tolerant: finds <td> with data-date/day and anchor titles.
    """
    soup = BeautifulSoup(html, "lxml")
    rows: List[EventRow] = []

    # Try table calendars first
    tds = soup.select("td[data-date], td[data-day], td[class*=day], td[class*=date]")
    for td in tds:
        anchors = td.select("a")
        if not anchors:
            continue
        # attempt to build a date_text from data-date or header context
        date_text = td.get("data-date") or td.get("data-day") or clean_text(td.get_text())
        for a in anchors:
            title = clean_text(a.get_text())
            href = urljoin(base_url, a.get("href") or "")
            if title and href:
                rows.append(EventRow(title=title, url=href, date_text=date_text, source=src_name, tzname=tzname))

    if rows:
        return rows

    # Fallback: any list entries with a date stamp and a link
    items = soup.select("li, .list, .event, .event-row")
    for it in items:
        a = it.select_one("a")
        if not a:
            continue
        title = clean_text(a.get_text())
        href = urljoin(base_url, a.get("href") or "")
        if not title or not href:
            continue
        # look for a nearby date-y text
        ctx = clean_text(it.get_text())
        rows.append(EventRow(title=title, url=href, date_text=ctx, source=src_name, tzname=tzname))

    return rows

def ingest_ics(text: str, base_url: str, src_name: str, tzname: str) -> Tuple[List[EventRow], Optional[str]]:
    """
    Best-effort ICS ingest with guard against HTML (blocked endpoints).
    We do not depend on ics lib parsing here; instead we scan VEVENT blocks
    to avoid strict grammar failures on imperfect feeds.
    """
    t = text.lstrip()
    if not t.startswith("BEGIN:VCALENDAR"):
        # Save what we got so you can inspect server behavior
        return [], "ICS endpoint returned non-ICS (likely HTML/blocked)"

    rows: List[EventRow] = []
    # Very light-weight VEVENT scan
    blocks = re.split(r"\nEND:VEVENT\s*", t, flags=re.IGNORECASE)
    for blk in blocks:
        if "BEGIN:VEVENT" not in blk:
            continue
        title = ""
        url = ""
        dtstart = ""
        dtend = ""
        loc = ""
        # simple unfolded lines
        lines = re.sub(r"\r\n?", "\n", blk)
        lines = re.sub(r"\n[ \t]", "", lines)  # unfold
        for line in lines.split("\n"):
            if line.upper().startswith("SUMMARY:"):
                title = clean_text(line.split(":", 1)[1])
            elif line.upper().startswith("DTSTART"):
                dtstart = clean_text(line.split(":", 1)[1])
            elif line.upper().startswith("DTEND"):
                dtend = clean_text(line.split(":", 1)[1])
            elif line.upper().startswith("LOCATION:"):
                loc = clean_text(line.split(":", 1)[1])
            elif line.upper().startswith("URL:"):
                url = clean_text(line.split(":", 1)[1])

        if title:
            rows.append(
                EventRow(
                    title=title,
                    url=url or base_url,
                    iso_hint=dtstart,
                    iso_end_hint=dtend,
                    location=loc,
                    source=src_name,
                    tzname=tzname,
                )
            )
    return rows, None

# ------------------------------ Normalize & Dedup ------------------------------ #

def normalize_rows(rows: Iterable[EventRow], default_duration_minutes: int = 120) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            # Prefer exact ISO hints if present; otherwise human date_text
            start_dt, end_dt, all_day = parse_datetime_range(
                date_text=r.date_text,
                iso_hint=r.iso_hint,
                iso_end_hint=r.iso_end_hint,
                tzname=r.tzname or CENTRAL_TZNAME,
            )
        except Exception:
            # very forgiving fallback: now..now+default
            tz = pytz.timezone(r.tzname or CENTRAL_TZNAME)
            start_dt = datetime.now(tz=tz)
            end_dt = start_dt + timedelta(minutes=default_duration_minutes)
            all_day = False

        out.append(
            {
                "title": r.title,
                "url": r.url,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "all_day": all_day,
                "location": r.location,
                "source": r.source,
            }
        )
    return out

def dedupe_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Cross-source dedupe by (title_normalized, date_only, url_normalized(optional)).
    If URL missing, rely on title+date_only.
    """
    seen = set()
    out = []
    for e in events:
        title_key = re.sub(r"\W+", " ", (e.get("title") or "").lower()).strip()
        start = e.get("start") or ""
        date_only = (start[:10] if len(start) >= 10 else start)
        url_key = (e.get("url") or "").strip().lower()
        key = (title_key, date_only, url_key)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out

# ------------------------------ Pipeline per source --------------------------- #

def run_source(src: SourceCfg) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "name": src.name,
        "url": src.url,
        "fetched": 0,
        "parsed": 0,
        "added": 0,
        "skipped_past": 0,
        "skipped_nodate": 0,
        "skipped_dupe": 0,
        "samples": [],
    }

    # Fetch primary page
    code, body, headers = fetch(src.url)
    stats["fetched"] = 1 if code else 0
    snap_raw = save_snapshot(f"{src.name}", body)
    stats["snapshot"] = snap_raw

    rows: List[EventRow] = []
    rest_error: Optional[str] = None
    ics_error: Optional[str] = None

    if code == 200:
        if src.kind == "modern_tribe":
            rows = parse_modern_tribe_html(body, src.url, src.name, src.tz)
        elif src.kind == "modern_tribe_rest":
            rows, rest_error = parse_modern_tribe_rest(src.url, src.name, src.tz, src.rest_window_days)
        elif src.kind == "growthzone":
            rows = parse_growthzone_html(body, src.url, src.name, src.tz)
        elif src.kind == "municipal_calendar":
            rows = parse_municipal_calendar_html(body, src.url, src.name, src.tz)
        elif src.kind == "ics":
            rows, ics_error = ingest_ics(body, src.url, src.name, src.tz)
        else:
            stats["error"] = f"Unknown kind '{src.kind}'"
    else:
        stats["error"] = f"HTTP {code}"

    # Optional ICS fallback if nothing found and ics_url provided
    if not rows and src.ics_url:
        c2, t2, _ = fetch(src.ics_url)
        if c2 == 200:
            ics_rows, ics_error = ingest_ics(t2, src.url, src.name, src.tz)
            # Save what server returned for debugging
            if t2:
                ext = ".ics" if t2.lstrip().startswith("BEGIN:VCALENDAR") else "_(ics_response).html"
                save_snapshot(f"{src.name} (ics)", t2, suffix=ext)
            rows = ics_rows
        else:
            stats["rest_error"] = stats.get("rest_error")
            ics_error = f"HTTP {c2} on {src.ics_url}"

    if rest_error:
        stats["rest_error"] = rest_error
    if ics_error:
        stats["ics_error"] = ics_error

    # Normalize + basic filtering (you can add a horizon if you want)
    normalized = normalize_rows(rows, default_duration_minutes=120)

    # Dedup happens later across all sources; here we just report
    stats["parsed"] = len(rows)
    stats["samples"] = [
        {
            "title": r["title"],
            "start": r["start"],
            "location": r.get("location", ""),
            "url": r["url"],
        }
        for r in normalized[:3]
    ]
    stats["_normalized"] = normalized  # keep for aggregation
    return stats

# --------------------------------- Main -------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="Path to sources.{yml,yaml}", default=None)
    args = ap.parse_args(argv)

    try:
        cfg_path = resolve_sources_path(args.config)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"[info] Using config: {cfg_path}")
    sources, defaults = load_sources(cfg_path)

    report: Dict[str, Any] = {
        "when": _now_iso(),
        "timezone": CENTRAL_TZNAME,
        "sources": [],
    }

    all_events: List[Dict[str, Any]] = []

    for src in sources:
        stats = run_source(src)
        report["sources"].append({k: v for k, v in stats.items() if k != "_normalized"})
        all_events.extend(stats.get("_normalized", []))

    # Cross-source dedupe
    deduped = dedupe_events(all_events)
    report["totals"] = {
        "normalized": len(all_events),
        "deduped": len(deduped),
    }

    # Persist report (so your workflow artifacts keep history)
    out_path = os.path.join(STATE_DIR, "last_run_report.json")
    write_json(out_path, report)
    print(f"[done] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
