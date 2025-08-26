# -*- coding: utf-8 -*-
"""
Northwoods Events – main aggregation runner.

Features:
- Loads sources from src/sources.yaml
- Fetches HTML (and optionally rendered HTML via Playwright if available)
- Parses events for:
    * Modern Tribe (TEC) – HTML, with REST fallback
    * GrowthZone – basic listings
    * Ai1EC – via parse_ai1ec
    * Travel Wisconsin widget – via parse_travelwi (if present)
    * ICS sources – direct ICS ingest
- Normalizes & de-dupes across sources and runs
- Writes:
    * docs/northwoods.ics (unified ICS)
    * state/events.json (persistent master store)
    * state/last_run_report.json (per-source stats)
    * state/new_items.json + state/daily_digest.{txt,html} (for email)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from bs4 import BeautifulSoup

# Local modules (must exist)
from normalize import clean_text, parse_datetime_range  # your existing normalizer
from icsbuild import build_ics                           # your existing ICS builder
from dedupe import stable_id                             # upgraded dedupe recommended
from tec_rest import fetch_events as tec_rest_fetch      # new TEC v6 REST fallback
from parse_ai1ec import parse_ai1ec                      # new Ai1EC parser

# Optional: Travel Wisconsin parser (only if you've added it)
try:
    from parse_travelwi import parse_travelwi  # noqa
except Exception:
    parse_travelwi = None  # type: ignore

# Optional: Playwright (rendered HTML). Code guards if not installed.
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# ---------- Paths ----------
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DOCS_DIR = ROOT / "docs"
STATE_DIR = ROOT / "state"
SNAP_DIR = STATE_DIR / "snapshots"

DOCS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
SNAP_DIR.mkdir(parents=True, exist_ok=True)

ICS_OUT = DOCS_DIR / "northwoods.ics"
EVENTS_STORE_PATH = STATE_DIR / "events.json"
LAST_RUN_REPORT = STATE_DIR / "last_run_report.json"
NEW_ITEMS_JSON = STATE_DIR / "new_items.json"
DIGEST_TXT = STATE_DIR / "daily_digest.txt"
DIGEST_HTML = STATE_DIR / "daily_digest.html"

SOURCES_YAML = SRC_DIR / "sources.yaml"

# ---------- Helpers / Types ----------
CHI = timezone(timedelta(hours=-5))  # America/Chicago (CDT). For absolute correctness, you can use zoneinfo if needed.

UA = "northwoods-events/1.0 (+github actions; https://github.com/dsundt/northwoods-events)"
REQ_TIMEOUT = 30

@dataclass
class Source:
    name: str
    type: str
    url: str
    wait_selector: Optional[str] = None
    ics_family: Optional[str] = None  # for ICS hints
    extra: Dict[str, Any] = None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def snapshot_html(name: str, raw_html: str, rendered: bool = False) -> str:
    safe = name.lower().replace(" ", "_").replace("/", "_").replace("&", "and")
    suffix = ".rendered.html" if rendered else ".html"
    out = SNAP_DIR / f"{safe}{suffix}"
    out.write_text(raw_html or "", encoding="utf-8", errors="ignore")
    return str(out.relative_to(ROOT))


# ---------- Fetchers ----------
def fetch_static(url: str, referer: Optional[str] = None) -> str:
    headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        headers["Referer"] = referer
    r = requests.get(url, headers=headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.text


def fetch_rendered(url: str, wait_selector: Optional[str] = None) -> str:
    """Render with Playwright if available; otherwise return empty string."""
    if not PLAYWRIGHT_AVAILABLE:
        return ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(user_agent=UA, java_script_enabled=True)
            page = context.new_page()
            page.set_default_timeout(30000)
            page.goto(url, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, state="visible", timeout=15000)
                except Exception:
                    # last resort: wait a bit more; some TEC apps lazy-load
                    page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
            return html
    except Exception:
        return ""


# ---------- Parsers ----------
def parse_modern_tribe_html(html: str) -> List[Dict]:
    """
    Lightweight Modern Tribe (TEC) list/month event extraction from HTML.
    REST fallback will catch what's missed.
    """
    items: List[Dict] = []
    soup = BeautifulSoup(html or "", "html.parser")

    # List view items
    nodes = soup.select(".tribe-events-calendar-list__event, .tribe-events-calendar-month__calendar-event")
    if not nodes:
        # Some older skins
        nodes = soup.select(".tribe-event, .type-tribe_events")

    for n in nodes:
        # title + link
        a = n.select_one("a.tribe-events-calendar-list__event-title-link, a.tribe-event-url, h3 a, .tribe-events-calendar-event__link, a")
        title = (a.get_text(strip=True) if a else "").strip()
        url = (a["href"].strip() if a and a.has_attr("href") else "")

        # date text
        dt = n.select_one("time, .tribe-events-calendar-list__event-date, .tribe-event-date-start")
        date_text = (dt.get_text(" ", strip=True) if dt else "").strip()

        # venue text
        venue = n.select_one(".tribe-events-venue, .tribe-venue, .tribe-events-calendar-list__event-venue, .tribe-events-venue-details")
        venue_text = (venue.get_text(" ", strip=True) if venue else "").strip()

        if title:
            items.append({
                "title": title,
                "url": url,
                "date_text": date_text,
                "venue_text": venue_text,
                "iso_datetime": "",
                "iso_end": "",
            })
    return items


def parse_growthzone_html(html: str) -> List[Dict]:
    """Very simple GrowthZone/ChamberMaster scraper."""
    items: List[Dict] = []
    soup = BeautifulSoup(html or "", "html.parser")
    cards = soup.select(".mn-event, .mn-event-card, .event, .listing .item, .mn-calendar .event")
    for n in cards:
        a = n.select_one("a")
        title = (a.get_text(strip=True) if a else "").strip()
        url = (a["href"].strip() if a and a.has_attr("href") else "")
        dateblock = n.select_one(".date, .mn-event-date, time, .when, .datetime")
        date_text = (dateblock.get_text(" ", strip=True) if dateblock else "").strip()
        venueblock = n.select_one(".venue, .location, .where, .mn-event-location")
        venue_text = (venueblock.get_text(" ", strip=True) if venueblock else "").strip()
        if title:
            items.append({
                "title": title,
                "url": url,
                "date_text": date_text,
                "venue_text": venue_text,
                "iso_datetime": "",
                "iso_end": "",
            })
    return items


def parse_by_type(kind: str, html: str) -> List[Dict]:
    k = (kind or "").lower()
    if k in ("modern_tribe", "modern-tribe", "tribe"):
        return parse_modern_tribe_html(html)
    if k in ("growthzone", "chambermaster"):
        return parse_growthzone_html(html)
    if k in ("ai1ec", "all_in_one", "all-in-one"):
        return parse_ai1ec(html)
    if k in ("travelwi", "travelwi_widget") and parse_travelwi is not None:
        return parse_travelwi(html)  # type: ignore
    return []


# ---------- ICS ingest ----------
def ingest_ics(text: str) -> List[Dict]:
    """
    Parse ICS text into normalized event rows (title, url, iso_datetime, iso_end, etc.)
    We keep iso_datetime/iso_end for precise times and set date_text='' so normalizer won't re-parse.
    """
    from ics import Calendar
    rows: List[Dict] = []
    cal = Calendar(text)
    for ev in cal.events:
        title = clean_text(getattr(ev, "name", "") or "")
        loc = clean_text(getattr(ev, "location", "") or "")
        link = ""
        try:
            link = getattr(ev, "url", "") or ""
        except Exception:
            link = ""
        start = ev.begin
        end = ev.end
        iso_start = ""
        iso_end = ""
        try:
            if start:
                iso_start = start.datetime.astimezone(timezone.utc).isoformat()
            if end:
                iso_end = end.datetime.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        if title and iso_start:
            rows.append({
                "title": title,
                "url": link,
                "date_text": "",
                "venue_text": loc,
                "iso_datetime": iso_start,
                "iso_end": iso_end,
            })
    return rows


# ---------- Normalization pipeline ----------
def normalize_rows(rows: List[Dict], default_duration_minutes: int) -> List[Dict]:
    """
    Turn raw rows into canonical event dicts used by store/ICS builder:
    {
      "id": <stable id>,
      "title": str,
      "start": datetime (tz-aware, UTC),
      "end": datetime (tz-aware, UTC),
      "location": str,
      "url": str,
      "all_day": bool,
      "source": str
    }
    """
    out: List[Dict] = []
    for r in rows:
        title = clean_text(r.get("title", ""))
        url = r.get("url", "") or ""
        venue_text = clean_text(r.get("venue_text", ""))

        iso_hint = r.get("iso_datetime") or ""
        iso_end_hint = r.get("iso_end") or ""
        date_text = r.get("date_text") or ""

        # parse date using your robust normalize.parse_datetime_range
        start_dt, end_dt, all_day = parse_datetime_range(date_text=date_text, iso_hint=iso_hint, iso_end_hint=iso_end_hint)

        if not start_dt:
            # Skip if no start can be determined
            continue

        # If no end, synthesize using default duration (but ensure end > start)
        if not end_dt:
            end_dt = start_dt + timedelta(minutes=default_duration_minutes)

        if end_dt <= start_dt:
            # Ensure valid interval
            end_dt = start_dt + timedelta(minutes=max(default_duration_minutes, 30))

        ev = {
            "title": title,
            "start": start_dt,
            "end": end_dt,
            "location": venue_text,
            "url": url,
            "all_day": bool(all_day),
        }
        out.append(ev)
    return out


# ---------- Store / Merge / Digest ----------
def load_events_store() -> Dict[str, Dict]:
    store = read_json(EVENTS_STORE_PATH, default={})
    # store is {id: event dict}, where datetimes are ISO strings; convert to Python for use if needed later
    return store


def serialize_event_for_store(ev: Dict[str, Any]) -> Dict[str, Any]:
    j = dict(ev)
    if isinstance(j.get("start"), datetime):
        j["start"] = j["start"].astimezone(timezone.utc).isoformat()
    if isinstance(j.get("end"), datetime):
        j["end"] = j["end"].astimezone(timezone.utc).isoformat()
    return j


def merge_events(store: Dict[str, Dict], new_events: List[Dict], source_name: str) -> Tuple[Dict[str, Dict], List[Dict]]:
    """
    Merge new normalized events into the store.
    Returns (updated_store, new_items_added_list)
    """
    added: List[Dict] = []
    for e in new_events:
        sid = stable_id(e["title"], e["start"].astimezone(timezone.utc).isoformat(), e.get("location", ""), e.get("url", ""))
        if sid in store:
            continue
        ev = dict(e)
        ev["source"] = source_name
        store[sid] = serialize_event_for_store(ev)
        added.append(ev)
    return store, added


def build_daily_digest(new_items: List[Dict]) -> None:
    """Write state/new_items.json and state/daily_digest.{txt,html}."""
    if not new_items:
        # Clean up any prior digest so email step skips sending
        for p in (NEW_ITEMS_JSON, DIGEST_TXT, DIGEST_HTML):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        return

    # Save machine-readable JSON
    safe_items = []
    for e in new_items:
        safe_items.append({
            "title": e["title"],
            "start": e["start"].astimezone(timezone.utc).isoformat(),
            "end": e["end"].astimezone(timezone.utc).isoformat(),
            "location": e.get("location", ""),
            "url": e.get("url", ""),
            "source": e.get("source", ""),
            "all_day": e.get("all_day", False),
        })
    save_json(NEW_ITEMS_JSON, safe_items)

    # Human-readable digest
    today = datetime.now(CHI).strftime("%Y-%m-%d")
    lines = ["New Northwoods Events added today:\n", f"{today}"]
    for e in new_items:
        s_local = e["start"].astimezone(CHI).strftime("%Y-%m-%d %I:%M %p %Z")
        e_local = e["end"].astimezone(CHI).strftime("%Y-%m-%d %I:%M %p %Z")
        lines.append(f"  Source: {e.get('source','')}")
        lines.append(f"    • {e['title']} @ {e.get('location','')}".rstrip())
        lines.append(f"      {s_local} – {e_local}")
        if e.get("url"):
            lines.append(f"      {e['url']}")
        lines.append("")
    DIGEST_TXT.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    # Minimal HTML version
    html_parts = [f"<h2>New Northwoods Events added today</h2><h3>{today}</h3><ul>"]
    for e in new_items:
        s_local = e["start"].astimezone(CHI).strftime("%Y-%m-%d %I:%M %p %Z")
        e_local = e["end"].astimezone(CHI).strftime("%Y-%m-%d %I:%M %p %Z")
        html_parts.append("<li>")
        html_parts.append(f"<div><strong>Source:</strong> {e.get('source','')}</div>")
        html_parts.append(f"<div><strong>{e['title']}</strong> @ {e.get('location','')}</div>")
        html_parts.append(f"<div>{s_local} – {e_local}</div>")
        if e.get("url"):
            html_parts.append(f'<div><a href="{e["url"]}">{e["url"]}</a></div>')
        html_parts.append("</li>")
    html_parts.append("</ul>")
    DIGEST_HTML.write_text("\n".join(html_parts), encoding="utf-8")


# ---------- Runner ----------
def main() -> None:
    start_ts = now_utc()

    cfg = load_yaml(SOURCES_YAML)
    tzname = cfg.get("timezone", "America/Chicago")
    default_duration = int(cfg.get("default_duration_minutes", 60))
    sources_raw = cfg.get("sources", [])

    sources: List[Source] = []
    for s in sources_raw:
        sources.append(Source(
            name=s.get("name"),
            type=s.get("type"),
            url=s.get("url"),
            wait_selector=s.get("wait_selector"),
            ics_family=s.get("ics_family"),
            extra={k: v for k, v in s.items() if k not in {"name", "type", "url", "wait_selector", "ics_family"}}
        ))

    events_store: Dict[str, Dict] = load_events_store()
    collected: List[Dict] = []
    total_new_items: List[Dict] = []

    report: Dict[str, Any] = {
        "when": datetime.now(CHI).isoformat(),
        "timezone": tzname,
        "sources": [],
    }

    # Playwright single context reuse (optional)
    playwright = None
    browser = None
    context = None
    if PLAYWRIGHT_AVAILABLE:
        try:
            p = sync_playwright().start()
            playwright = p
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(user_agent=UA, java_script_enabled=True)
            context.set_default_timeout(30000)
        except Exception:
            playwright = None
            browser = None
            context = None

    try:
        for s in sources:
            src_report = {
                "name": s.name,
                "url": s.url,
                "fetched": 0,
                "parsed": 0,
                "added": 0,
                "skipped_past": 0,
                "skipped_nodate": 0,
                "skipped_dupe": 0,
                "samples": [],
            }
            rows: List[Dict] = []
            static_html = ""
            rendered_html = ""
            snap_rel = ""
            snap_rendered_rel = ""

            try:
                stype = (s.type or "").lower()

                if stype == "ics":
                    # ICS direct ingest
                    headers = {"User-Agent": UA, "Accept": "text/calendar"}
                    r = requests.get(s.url, headers=headers, timeout=REQ_TIMEOUT)
                    r.raise_for_status()
                    txt = r.text
                    rows = ingest_ics(txt)
                    src_report["fetched"] = 1
                    src_report["parsed"] = len(rows)

                else:
                    # HTML path
                    static_html = fetch_static(s.url)
                    snap_rel = snapshot_html(s.name, static_html, rendered=False)

                    # Try HTML parse first
                    rows = parse_by_type(stype, static_html)

                    # If none found, try rendered (Playwright) when available
                    if len(rows) == 0 and context is not None:
                        page = context.new_page()
                        page.goto(s.url, wait_until="domcontentloaded")
                        if s.wait_selector:
                            try:
                                page.wait_for_selector(s.wait_selector, state="visible", timeout=15000)
                            except Exception:
                                page.wait_for_timeout(3000)
                        rendered_html = page.content()
                        page.close()
                        snap_rendered_rel = snapshot_html(s.name, rendered_html, rendered=True)
                        rows = parse_by_type(stype, rendered_html)

                    # TEC REST fallback if still nothing
                    if stype in ("modern_tribe", "modern-tribe", "tribe") and len(rows) == 0:
                        try:
                            api_rows = tec_rest_fetch(s.url, months_ahead=12)
                            rows.extend(api_rows)
                            src_report["rest_fallback"] = True
                        except Exception as e:
                            src_report["rest_error"] = repr(e)

                    src_report["fetched"] = 1
                    src_report["parsed"] = len(rows)

                # Normalize -> canonical events
                normalized = normalize_rows(rows, default_duration_minutes=default_duration)

                # Drop past events (older than now - 1 day grace)
                cutoff = now_utc() - timedelta(days=1)
                future_only = [e for e in normalized if e["end"].astimezone(timezone.utc) >= cutoff]

                # De-dupe across this run AND existing store
                seen_run = set()
                new_from_source: List[Dict] = []
                for e in future_only:
                    sid = stable_id(e["title"], e["start"].astimezone(timezone.utc).isoformat(), e.get("location", ""), e.get("url", ""))
                    if sid in seen_run:
                        src_report["skipped_dupe"] += 1
                        continue
                    seen_run.add(sid)

                    # Merge into persistent store
                    events_store, added_list = merge_events(events_store, [e], s.name)
                    if added_list:
                        new_from_source.extend(added_list)

                src_report["added"] = len(new_from_source)

                # Collect some sample titles for report
                for e in (new_from_source[:3] if new_from_source else normalized[:3]):
                    src_report["samples"].append({
                        "title": e["title"],
                        "start": e["start"].astimezone(timezone.utc).isoformat(),
                        "location": e.get("location", ""),
                        "url": e.get("url", ""),
                    })

                # Accumulate for ICS build (include everything in store at the end)
                total_new_items.extend(new_from_source)

            except requests.HTTPError as he:
                src_report["error"] = f"HTTPError({he})"
            except Exception as ex:
                src_report["error"] = repr(ex)
                src_report["traceback"] = traceback.format_exc()

            if snap_rel:
                src_report["snapshot"] = snap_rel
            if snap_rendered_rel:
                src_report["snapshot_rendered"] = snap_rendered_rel

            report["sources"].append(src_report)

        # Save updated store
        save_json(EVENTS_STORE_PATH, events_store)

        # Build unified ICS from the store (future events only)
        # Convert store (ISO strings) back to event objects for ICS builder
        future_events: List[Dict] = []
        for sid, ev in events_store.items():
            try:
                st = datetime.fromisoformat(ev["start"]).astimezone(timezone.utc)
                en = datetime.fromisoformat(ev["end"]).astimezone(timezone.utc)
                if en >= (now_utc() - timedelta(days=1)):
                    future_events.append({
                        "title": ev["title"],
                        "start": st,
                        "end": en,
                        "location": ev.get("location", ""),
                        "url": ev.get("url", ""),
                        "all_day": ev.get("all_day", False),
                        "source": ev.get("source", ""),
                    })
            except Exception:
                continue

        build_ics(future_events, ICS_OUT)

        # Build daily digest from only the new items detected this run
        build_daily_digest(total_new_items)

    finally:
        # Close Playwright if we opened it
        try:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
            if playwright is not None:
                playwright.stop()
        except Exception:
            pass

    # Write the run report
    save_json(LAST_RUN_REPORT, report)


if __name__ == "__main__":
    main()
