# -*- coding: utf-8 -*-
"""
Northwoods Events – main aggregation runner.

Outputs:
- docs/northwoods.ics
- state/events.json
- state/last_run_report.json
- state/new_items.json
- state/daily_digest.txt
- state/daily_digest.html
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from bs4 import BeautifulSoup

# Local modules
from normalize import clean_text, parse_datetime_range
from icsbuild import build_ics
from dedupe import stable_id
from tec_rest import fetch_events as tec_rest_fetch
from parse_ai1ec import parse_ai1ec  # present in repo

# Optional Travel Wisconsin parser
try:
    from parse_travelwi import parse_travelwi  # noqa: F401
except Exception:
    parse_travelwi = None  # type: ignore

# Optional Playwright rendering
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

# ---------- Misc ----------
CHI = timezone(timedelta(hours=-5))  # display tz for digest; UTC storage in store/ICS
UA = "northwoods-events/1.0 (+github actions; https://github.com/dsundt/northwoods-events)"
REQ_TIMEOUT = 30


@dataclass
class Source:
    name: str
    type: str
    url: str
    wait_selector: Optional[str] = None
    ics_family: Optional[str] = None
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
    safe = (
        name.lower()
        .replace(" ", "_").replace("/", "_").replace("&", "and")
        .replace("–", "-").replace("—", "-")
    )
    suffix = ".rendered.html" if rendered else ".html"
    out = SNAP_DIR / f"{safe}{suffix}"
    out.write_text(raw_html or "", encoding="utf-8", errors="ignore")
    return str(out.relative_to(ROOT))


# --- Compatibility wrapper for parse_datetime_range ---
def _call_parse_datetime_range(date_text: str, iso_hint: str, iso_end_hint: str):
    """
    Use whatever signature normalize.parse_datetime_range supports.
    Tries keywords first, then falls back to positional.
    """
    try:
        return parse_datetime_range(date_text=date_text, iso_hint=iso_hint, iso_end_hint=iso_end_hint)
    except TypeError:
        return parse_datetime_range(date_text, iso_hint, iso_end_hint)


# ---------- Fetchers ----------
def fetch_static(url: str, referer: Optional[str] = None) -> str:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    r = requests.get(url, headers=headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.text


def fetch_rendered_with_context(context, url: str, wait_selector: Optional[str] = None) -> str:
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded")
    if wait_selector:
        try:
            page.wait_for_selector(wait_selector, state="visible", timeout=15000)
        except Exception:
            page.wait_for_timeout(3000)
    html = page.content()
    page.close()
    return html


# ---------- Parsers ----------
def parse_modern_tribe_html(html: str) -> List[Dict]:
    items: List[Dict] = []
    soup = BeautifulSoup(html or "", "html.parser")

    nodes = soup.select(
        ".tribe-events-calendar-list__event, .tribe-events-calendar-month__calendar-event"
    )
    if not nodes:
        nodes = soup.select(".tribe-event, .type-tribe_events")

    for n in nodes:
        a = n.select_one(
            "a.tribe-events-calendar-list__event-title-link, "
            "a.tribe-event-url, "
            ".tribe-events-calendar-event__link, "
            "h3 a, a"
        )
        title = (a.get_text(strip=True) if a else "").strip()
        url = (a["href"].strip() if a and a.has_attr("href") else "")

        dt = n.select_one(
            "time, .tribe-events-calendar-list__event-date, .tribe-event-date-start"
        )
        date_text = (dt.get_text(" ", strip=True) if dt else "").strip()

        venue = n.select_one(
            ".tribe-events-venue, .tribe-venue, .tribe-events-calendar-list__event-venue, .tribe-events-venue-details"
        )
        venue_text = (venue.get_text(" ", strip=True) if venue else "").strip()

        if title:
            items.append(
                {
                    "title": title,
                    "url": url,
                    "date_text": date_text,
                    "venue_text": venue_text,
                    "iso_datetime": "",
                    "iso_end": "",
                }
            )
    return items


def parse_growthzone_html(html: str) -> List[Dict]:
    items: List[Dict] = []
    soup = BeautifulSoup(html or "", "html.parser")
    cards = soup.select(
        ".mn-event, .mn-event-card, .event, .listing .item, .mn-calendar .event"
    )
    for n in cards:
        a = n.select_one("a")
        title = (a.get_text(strip=True) if a else "").strip()
        url = (a["href"].strip() if a and a.has_attr("href") else "")
        dateblock = n.select_one(".date, .mn-event-date, time, .when, .datetime")
        date_text = (dateblock.get_text(" ", strip=True) if dateblock else "").strip()
        venueblock = n.select_one(".venue, .location, .where, .mn-event-location")
        venue_text = (venueblock.get_text(" ", strip=True) if venueblock else "").strip()
        if title:
            items.append(
                {
                    "title": title,
                    "url": url,
                    "date_text": date_text,
                    "venue_text": venue_text,
                    "iso_datetime": "",
                    "iso_end": "",
                }
            )
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
    Parse ICS text into normalized event rows.
    Safe against non-ICS text (returns []).
    """
    if not text or not text.lstrip().startswith("BEGIN:VCALENDAR"):
        return []
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
        start = getattr(ev, "begin", None)
        end = getattr(ev, "end", None)

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
            rows.append(
                {
                    "title": title,
                    "url": link,
                    "date_text": "",
                    "venue_text": loc,
                    "iso_datetime": iso_start,
                    "iso_end": iso_end,
                }
            )
    return rows


# ---------- Normalization ----------
def normalize_rows(rows: List[Dict], default_duration_minutes: int) -> List[Dict]:
    out: List[Dict] = []
    for r in rows:
        title = clean_text(r.get("title", ""))
        url = r.get("url", "") or ""
        venue_text = clean_text(r.get("venue_text", ""))

        iso_hint = r.get("iso_datetime") or ""
        iso_end_hint = r.get("iso_end") or ""
        date_text = r.get("date_text") or ""

        # IMPORTANT: call through wrapper; do NOT pass keyword args directly
        start_dt, end_dt, all_day = _call_parse_datetime_range(date_text, iso_hint, iso_end_hint)
        if not start_dt:
            continue

        if not end_dt:
            end_dt = start_dt + timedelta(minutes=default_duration_minutes)
        if end_dt <= start_dt:
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
    return read_json(EVENTS_STORE_PATH, default={})


def serialize_event_for_store(ev: Dict[str, Any]) -> Dict[str, Any]:
    j = dict(ev)
    if isinstance(j.get("start"), datetime):
        j["start"] = j["start"].astimezone(timezone.utc).isoformat()
    if isinstance(j.get("end"), datetime):
        j["end"] = j["end"].astimezone(timezone.utc).isoformat()
    return j


def merge_events(
    store: Dict[str, Dict], new_events: List[Dict], source_name: str
) -> Tuple[Dict[str, Dict], List[Dict]]:
    added: List[Dict] = []
    for e in new_events:
        sid = stable_id(
            e["title"],
            e["start"].astimezone(timezone.utc).isoformat(),
            e.get("location", ""),
            e.get("url", ""),
        )
        if sid in store:
            continue
        ev = dict(e)
        ev["source"] = source_name
        store[sid] = serialize_event_for_store(ev)
        added.append(ev)
    return store, added


def build_daily_digest(new_items: List[Dict]) -> None:
    if not new_items:
        for p in (NEW_ITEMS_JSON, DIGEST_TXT, DIGEST_HTML):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        return

    safe_items = []
    for e in new_items:
        safe_items.append(
            {
                "title": e["title"],
                "start": e["start"].astimezone(timezone.utc).isoformat(),
                "end": e["end"].astimezone(timezone.utc).isoformat(),
                "location": e.get("location", ""),
                "url": e.get("url", ""),
                "source": e.get("source", ""),
                "all_day": e.get("all_day", False),
            }
        )
    save_json(NEW_ITEMS_JSON, safe_items)

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
    cfg = load_yaml(SOURCES_YAML)
    tzname = cfg.get("timezone", "America/Chicago")
    default_duration = int(cfg.get("default_duration_minutes", 60))
    sources_raw = cfg.get("sources", [])

    sources: List[Source] = []
    for s in sources_raw:
        sources.append(
            Source(
                name=s.get("name"),
                type=s.get("type"),
                url=s.get("url"),
                wait_selector=s.get("wait_selector"),
                ics_family=s.get("ics_family"),
                extra={k: v for k, v in s.items() if k not in {"name", "type", "url", "wait_selector", "ics_family"}},
            )
        )

    events_store: Dict[str, Dict] = load_events_store()
    total_new_items: List[Dict] = []

    report: Dict[str, Any] = {
        "when": datetime.now(CHI).isoformat(),
        "timezone": tzname,
        "sources": [],
    }

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
                    headers = {"User-Agent": UA, "Accept": "text/calendar, text/plain, */*"}
                    r = requests.get(s.url, headers=headers, timeout=REQ_TIMEOUT)
                    r.raise_for_status()
                    txt = r.text or ""

                    ct = (r.headers.get("Content-Type") or "").lower()
                    looks_like_ics = txt.lstrip().startswith("BEGIN:VCALENDAR") or "text/calendar" in ct
                    if not looks_like_ics:
                        src_report["error"] = "ICS endpoint returned non-ICS (likely HTML/blocked)"
                        src_report["http_status"] = getattr(r, "status_code", None)
                        snap_rel = snapshot_html(s.name + " (ics_response)", txt, rendered=False)
                        rows = []
                    else:
                        rows = ingest_ics(txt)

                    src_report["fetched"] = 1
                    src_report["parsed"] = len(rows)

                else:
                    # HTML path
                    static_html = fetch_static(s.url)
                    snap_rel = snapshot_html(s.name, static_html, rendered=False)

                    # Try static parse
                    rows = parse_by_type(stype, static_html)

                    # Try rendered if needed
                    if len(rows) == 0 and context is not None:
                        try:
                            rendered_html = fetch_rendered_with_context(context, s.url, s.wait_selector)
                        except Exception:
                            rendered_html = ""
                        if rendered_html:
                            snap_rendered_rel = snapshot_html(s.name, rendered_html, rendered=True)
                            rows = parse_by_type(stype, rendered_html)

                    # TEC REST fallback if still empty
                    if stype in ("modern_tribe", "modern-tribe", "tribe") and len(rows) == 0:
                        try:
                            api_rows = tec_rest_fetch(s.url, months_ahead=12)
                            rows.extend(api_rows)
                            src_report["rest_fallback"] = True
                        except requests.HTTPError as he:
                            status = getattr(he.response, "status_code", None)
                            if status == 404:
                                src_report["rest_fallback_unavailable"] = True
                            else:
                                src_report["rest_error"] = f"HTTPError({he})"
                        except Exception as e:
                            src_report["rest_error"] = repr(e)

                    src_report["fetched"] = 1
                    src_report["parsed"] = len(rows)

                # Normalize
                normalized = normalize_rows(rows, default_duration_minutes=default_duration)

                # Keep future events (with 1-day grace)
                cutoff = now_utc() - timedelta(days=1)
                future_only = [
                    e for e in normalized if e["end"].astimezone(timezone.utc) >= cutoff
                ]

                # Merge into store (cross-source de-dupe via stable_id)
                seen_run = set()
                new_from_source: List[Dict] = []
                for e in future_only:
                    sid = stable_id(
                        e["title"],
                        e["start"].astimezone(timezone.utc).isoformat(),
                        e.get("location", ""),
                        e.get("url", ""),
                    )
                    if sid in seen_run:
                        src_report["skipped_dupe"] += 1
                        continue
                    seen_run.add(sid)

                    events_store, added_list = merge_events(events_store, [e], s.name)
                    if added_list:
                        new_from_source.extend(added_list)

                src_report["added"] = len(new_from_source)

                # Samples (either new or first 3 normalized)
                for e in (new_from_source[:3] if new_from_source else normalized[:3]):
                    src_report["samples"].append(
                        {
                            "title": e["title"],
                            "start": e["start"].astimezone(timezone.utc).isoformat(),
                            "location": e.get("location", ""),
                            "url": e.get("url", ""),
                        }
                    )

                # Aggregate newly added for digest
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

        # Save store
        save_json(EVENTS_STORE_PATH, events_store)

        # Build ICS from store (future events only)
        future_events: List[Dict] = []
        for sid, ev in events_store.items():
            try:
                st = datetime.fromisoformat(ev["start"]).astimezone(timezone.utc)
                en = datetime.fromisoformat(ev["end"]).astimezone(timezone.utc)
                if en >= (now_utc() - timedelta(days=1)):
                    future_events.append(
                        {
                            "title": ev["title"],
                            "start": st,
                            "end": en,
                            "location": ev.get("location", ""),
                            "url": ev.get("url", ""),
                            "all_day": ev.get("all_day", False),
                            "source": ev.get("source", ""),
                        }
                    )
            except Exception:
                continue

        build_ics(future_events, ICS_OUT)

        # Build digest for newly added items
        build_daily_digest(total_new_items)

    finally:
        # Close Playwright if opened
        try:
            if 'context' in locals() and context is not None:
                context.close()
        except Exception:
            pass
        try:
            if 'browser' in locals() and browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            if 'playwright' in locals() and playwright is not None:
                playwright.stop()
        except Exception:
            pass

    # Write run report
    save_json(LAST_RUN_REPORT, report)


if __name__ == "__main__":
    main()
