# src/main.py
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---- Local helpers (existing in your repo) ----
# normalize.py must provide:
#   - parse_datetime_range(date_text=..., iso_hint=..., iso_end_hint=..., tzname=...)
#   - clean_text(s)
from normalize import parse_datetime_range, clean_text

# New parsers we added
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.squarespace import parse_squarespace

# Optional: if you have an ai1ec parser file, import it; otherwise we stub it below.
try:
    from parsers.parse_ai1ec import parse_ai1ec  # noqa: F401
except Exception:
    def parse_ai1ec(url: str) -> List[Dict]:
        return []

CENTRAL_TZ = "America/Chicago"

UA = "northwoods-events (+https://github.com/dsundt/northwoods-events)"
REQ_HEADERS = {"User-Agent": UA}

STATE_DIR = Path("state")
SNAP_DIR = STATE_DIR / "snapshots"
SNAP_DIR.mkdir(parents=True, exist_ok=True)


# ------------------- Utilities -------------------

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _save_text_snapshot(name_hint: str, text: str, suffix: str = ".html") -> str:
    """Save a debugging snapshot under state/snapshots and return its path."""
    safe = re.sub(r"[^a-z0-9_.()\- ]+", "_", name_hint.lower())
    p = SNAP_DIR / f"{safe}{suffix}"
    p.write_text(text, encoding="utf-8", errors="ignore")
    return str(p)


def _http_get(url: str, *, allow_redirects: bool = True, session: Optional[requests.Session] = None) -> requests.Response:
    s = session or requests.Session()
    r = s.get(url, headers=REQ_HEADERS, timeout=30, allow_redirects=allow_redirects)
    r.raise_for_status()
    return r


def _rows_to_normalized(rows: List[Dict], default_tz: str = CENTRAL_TZ, default_duration_minutes: int = 120) -> List[Dict]:
    """
    Normalize the parser rows into unified dicts with parsed datetimes.
    Each row should have: title, date_text, iso_hint, iso_end_hint, location, url, source, tzname
    """
    out: List[Dict] = []
    for r in rows:
        title = clean_text(r.get("title", ""))
        if not title:
            continue
        date_text = r.get("date_text", "") or ""
        iso_hint = r.get("iso_hint")
        iso_end_hint = r.get("iso_end_hint")
        tzname = r.get("tzname") or default_tz

        start_dt, end_dt, all_day = parse_datetime_range(
            date_text=date_text,
            iso_hint=iso_hint,
            iso_end_hint=iso_end_hint,
            tzname=tzname,
        )

        out.append({
            "title": title,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "all_day": bool(all_day),
            "location": clean_text(r.get("location", "")),
            "url": r.get("url") or r.get("source") or "",
            "source": r.get("source") or "",
        })
    return out


def _dedupe_normalized(rows: List[Dict]) -> Tuple[List[Dict], int]:
    """
    De-duplicate across ALL sources by (title_norm, date_start, location_norm).
    Returns (unique_rows, dup_count)
    """
    seen = set()
    unique: List[Dict] = []
    dup = 0
    for r in rows:
        key = (r["title"].strip().lower(), r["start"], (r.get("location") or "").strip().lower())
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        unique.append(r)
    return unique, dup


# ------------------- Parsers (HTML/ICS) -------------------

def parse_modern_tribe_html_list(url: str, session: Optional[requests.Session] = None) -> List[Dict]:
    """
    Robust HTML list parser for Modern Tribe / The Events Calendar (works with legacy '.tribe-' and new '.tec-' classes).
    Avoids the /wp-json/ REST which is often blocked.
    """
    s = session or requests.Session()
    resp = _http_get(url, session=s)
    html = resp.text
    _save_text_snapshot("modern_tribe_list", html)

    soup = BeautifulSoup(html, "lxml")

    # New TEC v6+ often uses .tec-events, older uses .tribe-events
    containers = soup.select(".tec-events, .tribe-events")
    if not containers:
        containers = [soup]

    rows: List[Dict] = []

    def _text(el) -> str:
        return clean_text(el.get_text(" ", strip=True)) if el else ""

    for root in containers:
        # Common per-event wrappers:
        #  - article.tribe-events-calendar-list__event
        #  - .tec-event, .tec-list-event, li.tribe-events-list-event
        candidates = []
        candidates += root.select("article.tribe-events-calendar-list__event, li.tribe-events-list-event")
        candidates += root.select(".tec-event, .tec-list__item, .tec-list-event, .tec-archive__event-row")

        if not candidates:
            # Fallback: any link under events list region
            candidates = root.select("a.tribe-events-calendar-list__event-title-link, a.tec-event__title-link, .tribe-events a, .tec-events a")

        for ev in candidates:
            # Title + link
            a = None
            for sel in [
                "a.tribe-events-calendar-list__event-title-link",
                "a.tec-event__title-link",
                "h3 a", "h2 a", "a.tribe-event-title", "a",
            ]:
                a = ev.select_one(sel) if hasattr(ev, "select_one") else None
                if a:
                    break
            if not a and hasattr(ev, "find"):
                a = ev.find("a", href=True)
            if not a:
                continue

            title = _text(a) or _text(ev)
            link = urljoin(url, a.get("href", ""))

            # Date text: look for time/date elements
            date_text = ""
            for sel in [
                "time", ".tribe-event-date-start", ".tribe-events-event-datetime",
                ".tribe-event-date", ".tec-event__date", ".tec-event__datetime",
                ".tec-event__schedule", ".tec-list__event-date", ".tec-event-date"
            ]:
                el = ev.select_one(sel) if hasattr(ev, "select_one") else None
                if el:
                    date_text = _text(el)
                    if date_text:
                        break

            if not date_text:
                # Fallback: shallow search around
                parent = ev if hasattr(ev, "find_parent") else None
                near = parent or ev
                if near and hasattr(near, "find_all"):
                    for sm in near.find_all(["time", "span", "div", "p"]):
                        t = _text(sm)
                        if re.search(r"\b(am|pm|\d{4}|\bJan|\bFeb|\bMar|\bApr|\bMay|\bJun|\bJul|\bAug|\bSep|\bOct|\bNov|\bDec)", t, re.I):
                            date_text = t
                            break

            # Location best effort
            location = ""
            for sel in [
                ".tribe-events-venue__name", ".tribe-venue", ".tec-event__venue", ".tec-venue", ".tribe-events-venue-details"
            ]:
                el = ev.select_one(sel) if hasattr(ev, "select_one") else None
                if el:
                    location = _text(el)
                    break

            rows.append({
                "title": title,
                "date_text": date_text,
                "iso_hint": None,
                "iso_end_hint": None,
                "location": location,
                "url": link,
                "source": url,
                "tzname": CENTRAL_TZ,
            })

    return rows


def ingest_ics(url: str, session: Optional[requests.Session] = None) -> List[Dict]:
    """
    Light ICS ingestion with safety checks (a lot of sites serve HTML to bots).
    Returns rows in the common schema; normalize.py will turn iso into local dt.
    """
    s = session or requests.Session()
    r = _http_get(url, session=s)
    txt = r.text

    # Quick sanity: ICS should begin with BEGIN:VCALENDAR (allow BOM/whitespace)
    head = txt.lstrip()[:32].upper()
    if "BEGIN:VCALENDAR" not in head:
        # Save the response for debugging and return empty with a flagged message in report.
        _save_text_snapshot(Path(url).name + "_(ics_response)", txt, suffix=".html")
        raise ValueError("ICS endpoint returned non-ICS (likely HTML/blocked)")

    # Very lightweight parse to VEVENT blocks
    rows: List[Dict] = []
    blocks = re.split(r"(?mi)^BEGIN:VEVENT\s*$", txt)[1:]
    for b in blocks:
        # Title
        msum = re.search(r"(?mi)^SUMMARY:(.*)$", b)
        title = clean_text(msum.group(1)) if msum else ""

        # DTSTART / DTEND (ISO-ish; we'll pass as iso_hint)
        mstart = re.search(r"(?mi)^DTSTART(?:;[^:]+)?:([0-9TZ+\-:]+)", b)
        mend = re.search(r"(?mi)^DTEND(?:;[^:]+)?:([0-9TZ+\-:]+)", b)
        iso_start = mstart.group(1) if mstart else None
        iso_end = mend.group(1) if mend else None

        # URL or LOCATION
        murl = re.search(r"(?mi)^URL:(.*)$", b)
        mloc = re.search(r"(?mi)^LOCATION:(.*)$", b)

        rows.append({
            "title": title or "(No Title)",
            "date_text": f"{iso_start or ''} – {iso_end or ''}".strip(),
            "iso_hint": iso_start,
            "iso_end_hint": iso_end,
            "location": clean_text(mloc.group(1)) if mloc else "",
            "url": (murl.group(1).strip() if murl else url),
            "source": url,
            "tzname": CENTRAL_TZ,
        })

    return rows


# ------------------- Main orchestration -------------------

@dataclass
class Source:
    name: str
    type: str
    url: str
    enabled: bool = True
    ics_url: Optional[str] = None


def load_sources(yaml_path: str = "sources.yaml") -> List[Source]:
    import yaml
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    out: List[Source] = []
    for item in data:
        if not item or not isinstance(item, dict):
            continue
        if not item.get("enabled", True):
            continue
        out.append(Source(
            name=item["name"],
            type=item["type"],
            url=item["url"],
            enabled=item.get("enabled", True),
            ics_url=item.get("ics_url"),
        ))
    return out


def collect_for_source(src: Source) -> Tuple[List[Dict], Dict]:
    """
    Returns (normalized_rows, meta_report)
    meta_report records parsed counts / errors / snapshot paths for last_run_report.json
    """
    meta = {
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

    session = requests.Session()
    session.headers.update(REQ_HEADERS)

    rows: List[Dict] = []
    html_snapshot_path = None
    err = None
    rest_error = None

    try:
        if src.type == "modern_tribe":
            resp = _http_get(src.url, session=session)
            html_snapshot_path = _save_text_snapshot(
                re.sub(r"[^a-z0-9_.()\- ]+", "_", src.name.lower()) + "_.html",
                resp.text,
            )
            meta["fetched"] = 1
            rows = parse_modern_tribe_html_list(src.url, session=session)

        elif src.type in ("growthzone", "micronet", "micronet_growthzone"):
            rows = parse_growthzone(src.url, session=session)
            meta["fetched"] = 1

        elif src.type == "simpleview":
            rows = parse_simpleview(src.url, session=session)
            meta["fetched"] = 1

        elif src.type in ("squarespace", "sqs"):
            rows = parse_squarespace(src.url, session=session)
            meta["fetched"] = 1

        elif src.type == "ai1ec":
            rows = parse_ai1ec(src.url)
            meta["fetched"] = 1

        elif src.type == "ics":
            rows = ingest_ics(src.url, session=session)
            meta["fetched"] = 1

        else:
            err = f"Unknown source type: {src.type}"

    except requests.HTTPError as e:
        rest_error = f"HTTPError({e})"
    except ValueError as e:
        # e.g., ICS endpoint returned HTML
        err = str(e)
    except Exception as e:
        err = f"{e.__class__.__name__}('{e}')"

    # Normalize & dedupe (per-source)
    normalized: List[Dict] = []
    if rows:
        try:
            normalized = _rows_to_normalized(rows, default_tz=CENTRAL_TZ)
        except Exception as e:
            err = f"NormalizeError: {e.__class__.__name__}('{e}')"

    meta["parsed"] = len(rows)
    if html_snapshot_path:
        meta["snapshot"] = html_snapshot_path

    if rest_error:
        meta["rest_error"] = rest_error
    if err:
        meta["error"] = err

    # Show a few samples for debugging
    if normalized:
        meta["added"] = len(normalized)
        meta["samples"] = [
            {
                "title": r["title"],
                "start": r["start"],
                "location": r.get("location", ""),
                "url": r.get("url", ""),
            }
            for r in normalized[:3]
        ]

    return normalized, meta


def main() -> int:
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(SNAP_DIR, exist_ok=True)

    sources = load_sources("sources.yaml")

    all_rows: List[Dict] = []
    report = {
        "when": _now_iso(),
        "timezone": CENTRAL_TZ,
        "sources": [],
    }

    # Collect per source
    for src in sources:
        rows, meta = collect_for_source(src)
        report["sources"].append(meta)
        all_rows.extend(rows)

    # Cross-source de-duplication
    unique, dup = _dedupe_normalized(all_rows)

    # Write last_run_report.json
    (STATE_DIR / "last_run_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    # Persist merged normalized events as a JSON for your later steps (ICS/email builders)
    (STATE_DIR / "normalized_events.json").write_text(
        json.dumps({"count": len(unique), "deduped": dup, "items": unique}, indent=2),
        encoding="utf-8"
    )

    print(f"Collected {len(all_rows)} rows; {len(unique)} after de-dup (removed {dup}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
