#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytz
import requests
import yaml
from bs4 import BeautifulSoup

# If you have src/normalize.py from earlier, we’ll use it.
# It provides: parse_datetime_range(date_text|positional, iso_hint, iso_end_hint, tzname)
try:
    from normalize import parse_datetime_range, clean_text  # type: ignore
except Exception:
    # Tiny safe fallbacks if normalize.py is missing (not as robust)
    def clean_text(s: Optional[str]) -> str:
        if not s:
            return ""
        s = re.sub(r"\s+", " ", s.strip())
        return s.replace("\u200b", "")

    def parse_datetime_range(*args, **kwargs):
        # Absolute fallback: treat everything as all-day today
        tz = pytz.timezone(kwargs.get("tzname") or "America/Chicago")
        start = tz.localize(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        end = start + timedelta(days=1) - timedelta(seconds=1)
        return start, end, True


CENTRAL = pytz.timezone("America/Chicago")
REQ_TIMEOUT = 30
HEADERS = {
    "User-Agent": "northwoods-events/1.0 (+https://github.com/dsundt/northwoods-events)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

STATE_DIR = "state"
SNAP_DIR = os.path.join(STATE_DIR, "snapshots")
OUT_ICS = "northwoods-events.ics"
OUT_JSON = os.path.join(STATE_DIR, "last_run_report.json")


@dataclass
class Row:
    title: str
    url: str
    date_text: str = ""
    iso_hint: str = ""
    iso_end_hint: str = ""
    location: str = ""
    tzname: str = "America/Chicago"
    source: str = ""


@dataclass
class Normalized:
    title: str
    url: str
    start: str
    end: str
    all_day: bool
    location: str
    source: str


# -----------------------
# Helpers
# -----------------------
def ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(SNAP_DIR, exist_ok=True)


def now_iso() -> str:
    return datetime.now(CENTRAL).isoformat()


def save_snapshot(name: str, content: str, rendered: bool = False) -> str:
    safe = re.sub(r"[^a-z0-9._\-() ]+", "_", name.lower())
    suffix = ".rendered.html" if rendered else ".html"
    path = os.path.join(SNAP_DIR, f"{safe}{suffix}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def get_text(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[str, int, Dict[str, str]]:
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    r = requests.get(url, headers=h, timeout=REQ_TIMEOUT)
    return r.text, r.status_code, dict(r.headers)


def make_ics_url_from_events_list_url(url: str) -> str:
    # Most Modern Tribe and many WP calendars expose ?ical=1 on same path
    if "?" in url:
        base = url.split("?")[0]
    else:
        base = url
    return f"{base}?ical=1"


def tribe_rest_root(url: str) -> str:
    # Build /wp-json/tribe/events/v1/events root from a page URL
    # e.g., https://example.com/events/?eventDisplay=list -> https://example.com/wp-json/tribe/events/v1/events
    m = re.match(r"^(https?://[^/]+)/", url)
    if not m:
        return ""
    root = m.group(1)
    return root + "/wp-json/tribe/events/v1/events"


def to_local(dt: datetime, tzname: str) -> datetime:
    tz = pytz.timezone(tzname or "America/Chicago")
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt.astimezone(tz)


def normalize_rows(rows: List[Row], default_duration_minutes: int = 120) -> List[Normalized]:
    out: List[Normalized] = []
    for r in rows:
        # Try new-style kwargs call first; if the normalize module is the earlier version,
        # we fall back to positional.
        try:
            start_dt, end_dt, all_day = parse_datetime_range(
                date_text=r.date_text,
                iso_hint=r.iso_hint,
                iso_end_hint=r.iso_end_hint,
                tzname=r.tzname or "America/Chicago",
            )
        except TypeError:
            # old signature fallback
            try:
                start_dt, end_dt, all_day = parse_datetime_range(
                    r.date_text, r.iso_hint, r.iso_end_hint
                )
            except Exception:
                # last chance: assume default duration from iso_hint or now
                if r.iso_hint:
                    try:
                        start_dt, _, _ = parse_datetime_range(r.iso_hint, "", "")
                        end_dt = start_dt + timedelta(minutes=default_duration_minutes)
                        all_day = False
                    except Exception:
                        start_dt = to_local(datetime.now(), r.tzname)
                        end_dt = start_dt + timedelta(minutes=default_duration_minutes)
                        all_day = False
                else:
                    start_dt = to_local(datetime.now(), r.tzname)
                    end_dt = start_dt + timedelta(minutes=default_duration_minutes)
                    all_day = False

        # Enforce timezone
        start_dt = to_local(start_dt, r.tzname)
        end_dt = to_local(end_dt, r.tzname)

        out.append(
            Normalized(
                title=clean_text(r.title),
                url=r.url,
                start=start_dt.isoformat(),
                end=end_dt.isoformat(),
                all_day=bool(all_day),
                location=clean_text(r.location or ""),
                source=r.source,
            )
        )
    return out


def dedupe_events(items: List[Normalized]) -> List[Normalized]:
    seen = set()
    keep: List[Normalized] = []
    for it in items:
        key = (it.title.lower().strip(), it.start[:10])  # same title + same start date (local)
        if key not in seen:
            keep.append(it)
            seen.add(key)
    return keep


# -----------------------
# Parsers
# -----------------------
def parse_modern_tribe(source_name: str, url: str, tzname: str) -> Dict[str, Any]:
    """
    Try in order:
      1) Tribe REST API
      2) HTML scrape
      3) ICS fallback (if enabled by caller)
    """
    report: Dict[str, Any] = {"name": source_name, "url": url, "fetched": 0, "parsed": 0}
    rows: List[Row] = []

    # 1) REST
    try:
        api = tribe_rest_root(url)
        if api:
            params = {
                "page": 1,
                "per_page": 100,
                # generous window: yesterday .. + 1 year
                "start_date": (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z",
                "end_date": (datetime.utcnow() + timedelta(days=365)).isoformat() + "Z",
            }
            page = 1
            total = 0
            while True:
                params["page"] = page
                txt, status, hdrs = get_text(api, headers={"Accept": "application/json"})
                # The Tribe API needs query string; requests above missed it if we didn't pass params to GET.
                # Do a proper GET with params:
                r = requests.get(api, params=params, headers={"Accept": "application/json", **HEADERS}, timeout=REQ_TIMEOUT)
                status = r.status_code
                txt = r.text
                if status != 200:
                    if status == 404:
                        report["rest_fallback_unavailable"] = True
                    else:
                        report["rest_error"] = f"HTTP {status}"
                    break
                data = r.json()
                events = data.get("events", [])
                if not events:
                    break
                for ev in events:
                    title = ev.get("title", "")
                    link = ev.get("url") or ev.get("website", url)
                    iso = ev.get("start_date") or ev.get("start", "")
                    iso_end = ev.get("end_date") or ev.get("end", "")
                    venue = ""
                    v = ev.get("venue") or {}
                    if isinstance(v, dict):
                        venue = v.get("address", "") or v.get("venue", "")
                    rows.append(Row(
                        title=title,
                        url=link or url,
                        date_text="",
                        iso_hint=iso or "",
                        iso_end_hint=iso_end or "",
                        location=venue,
                        tzname=tzname,
                        source=source_name,
                    ))
                total += len(events)
                page += 1
                # Stop after 10 pages just in case
                if page > 10:
                    break
            if total > 0:
                report["fetched"] = 1
                report["parsed"] = total
                return {"rows": rows, "report": report}
    except Exception as e:
        report["rest_error"] = repr(e)

    # 2) HTML scrape (list page)
    try:
        txt, status, hdrs = get_text(url)
        report["fetched"] = 1
        save_snapshot(f"{source_name}", txt, rendered=False)
        soup = BeautifulSoup(txt, "lxml")

        # Common patterns on Tribe list pages:
        # - article.tribe_events, article.type-tribe_events
        # - a.tribe-event-url
        # - time[itemprop=startDate]
        articles = soup.select("article.type-tribe_events, article.tribe_events")
        if not articles:
            # Try generic cards
            articles = soup.select("[data-tribe-event-id], .tribe-common-c-card")
        for art in articles:
            a = art.select_one("a.tribe-event-url, a.url, a[href*='/event/']")
            if not a:
                continue
            link = a.get("href") or url
            title = clean_text(a.get_text())
            # Try to extract time info
            time_tag = art.select_one("time[itemprop='startDate'], time.tribe-event-date-start")
            date_text = ""
            iso = ""
            if time_tag:
                iso = (time_tag.get("datetime") or "").strip()
                if not iso:
                    date_text = clean_text(time_tag.get_text())

            # location if present
            loc = ""
            loc_tag = art.select_one(".tribe-event-venue, .tribe-events-venue__meta, [class*='venue'], .location")
            if loc_tag:
                loc = clean_text(loc_tag.get_text())

            rows.append(Row(
                title=title or "(untitled)",
                url=link,
                date_text=date_text,
                iso_hint=iso,
                iso_end_hint="",
                location=loc,
                tzname=tzname,
                source=source_name,
            ))
        report["parsed"] = len(rows)
        if rows:
            return {"rows": rows, "report": report}
    except Exception as e:
        report["error_html"] = repr(e)

    # 3) Caller may try ICS fallback next
    return {"rows": [], "report": report}


def parse_growthzone(source_name: str, url: str, tzname: str) -> Dict[str, Any]:
    """
    Basic GrowthZone calendar scraper for the listing page.
    If only day cells are available, we collect event URLs and fetch details.
    """
    report: Dict[str, Any] = {"name": source_name, "url": url, "fetched": 0, "parsed": 0}
    rows: List[Row] = []

    try:
        txt, status, hdrs = get_text(url)
        report["fetched"] = 1
        save_snapshot(f"{source_name}", txt)
        soup = BeautifulSoup(txt, "lxml")

        # Pattern 1: list view entries
        items = soup.select(".gz-event-list-item, .event-listing, .gz-event, .event-item, .item-event")
        # Pattern 2: calendar cells with links
        if not items:
            items = soup.select("a[href*='/events/details/'], a[href*='/events/details/']")

        links: List[str] = []
        for it in items:
            a = it if it.name == "a" else it.find("a", href=True)
            if not a:
                continue
            href = a.get("href")
            if not href:
                continue
            if href.startswith("/"):
                m = re.match(r"^(https?://[^/]+)/", url)
                if m:
                    href = m.group(1) + href
            links.append(href)

        links = sorted(set(links))
        # If nothing found, try to read inline JSON
        if not links:
            for a in soup.find_all("a", href=True):
                if "/events/details/" in a["href"]:
                    href = a["href"]
                    if href.startswith("/"):
                        m = re.match(r"^(https?://[^/]+)/", url)
                        if m:
                            href = m.group(1) + href
                    links.append(href)
            links = sorted(set(links))

        # Fetch each detail page and extract title/date
        for href in links[:50]:
            try:
                dtxt, st, hh = get_text(href)
                dsoup = BeautifulSoup(dtxt, "lxml")
                title = clean_text(
                    (dsoup.select_one("h1") or dsoup.select_one(".event-title") or dsoup.title or {}).get_text() if (dsoup.select_one("h1") or dsoup.select_one(".event-title") or dsoup.title) else ""
                )
                if not title:
                    title = "(untitled)"

                # Date/time extraction heuristics
                # Try <time datetime> first
                time_tag = dsoup.select_one("time[datetime]")
                iso = time_tag.get("datetime").strip() if time_tag and time_tag.has_attr("datetime") else ""
                date_text = ""
                if not iso:
                    # Look for recognizable date strings on the page
                    dt_block = dsoup.select_one(".event-date, .date, .gz-event-date, .event-details__date, .time")
                    date_text = clean_text(dt_block.get_text()) if dt_block else clean_text(dsoup.get_text()[:4000])

                loc = ""
                loc_tag = dsoup.select_one(".event-location, .location, .venue, .gz-event-location")
                if loc_tag:
                    loc = clean_text(loc_tag.get_text())

                rows.append(Row(
                    title=title,
                    url=href,
                    date_text=date_text,
                    iso_hint=iso,
                    iso_end_hint="",
                    location=loc,
                    tzname=tzname,
                    source=source_name,
                ))
            except Exception:
                continue

        report["parsed"] = len(rows)
    except Exception as e:
        report["error"] = repr(e)

    return {"rows": rows, "report": report}


def parse_municipal_calendar(source_name: str, url: str, tzname: str) -> Dict[str, Any]:
    """
    Generic municipal calendar scraper (like Town of Arbor Vitae).
    Tries multiple selectors for titles, links, dates.
    """
    report: Dict[str, Any] = {"name": source_name, "url": url, "fetched": 0, "parsed": 0}
    rows: List[Row] = []

    try:
        txt, status, hdrs = get_text(url)
        report["fetched"] = 1
        save_snapshot(f"{source_name}", txt)
        soup = BeautifulSoup(txt, "lxml")

        # Common WP calendar/table plugins: look for anchors in calendar/list sections
        candidates = soup.select(
            ".calendar a, .events a, .ai1ec-event-title a, a.event, a[href*='/event/'], a[href*='?event']"
        )
        if not candidates:
            # Try generic list items
            candidates = soup.select("li a, .entry-content a")

        for a in candidates:
            href = a.get("href") or url
            title = clean_text(a.get_text()) or "(untitled)"
            # Nearby text might have date
            holder = a.find_parent(["li", "div", "tr"]) or a
            dt_text = clean_text(holder.get_text())
            rows.append(Row(
                title=title,
                url=href,
                date_text=dt_text,
                iso_hint="",
                iso_end_hint="",
                location="",
                tzname=tzname,
                source=source_name,
            ))

        report["parsed"] = len(rows)
    except Exception as e:
        report["error"] = repr(e)

    return {"rows": rows, "report": report}


def ingest_ics_text(source_name: str, ics_text: str, tzname: str) -> Dict[str, Any]:
    """
    Parse ICS text using a simple line parser (no ics lib dependency) to avoid
    failures when hosts return HTML with 200 OK.
    """
    report: Dict[str, Any] = {"name": source_name, "fetched": 0, "parsed": 0}
    rows: List[Row] = []

    txt = ics_text.strip()
    if not txt.startswith("BEGIN:VCALENDAR"):
        report["error"] = "ICS endpoint returned non-ICS (likely HTML/blocked)"
        # Save what we got for debugging
        save_snapshot(f"{source_name} (ics) (ics_response)", ics_text)
        return {"rows": [], "report": report}

    # Unfold lines per RFC (join lines starting with space)
    lines = []
    for raw in txt.splitlines():
        if raw.startswith(" "):
            if lines:
                lines[-1] += raw[1:]
        else:
            lines.append(raw)

    cur: Dict[str, str] = {}
    in_event = False
    parsed = 0

    def flush():
        nonlocal parsed
        if not cur:
            return
        title = cur.get("SUMMARY", "").strip()
        url = cur.get("URL", "").strip() or cur.get("UID", "").strip() or ""
        dtstart = cur.get("DTSTART", "").strip()
        dtend = cur.get("DTEND", "").strip()
        loc = cur.get("LOCATION", "").strip()
        rows.append(Row(
            title=title or "(untitled)",
            url=url or "",
            date_text="", iso_hint=dtstart, iso_end_hint=dtend,
            location=loc, tzname=tzname, source=source_name
        ))
        parsed += 1

    for ln in lines:
        if ln == "BEGIN:VEVENT":
            in_event = True
            cur = {}
        elif ln == "END:VEVENT":
            in_event = False
            flush()
            cur = {}
        elif in_event:
            # split name:params:value — we only need the left-most name and value
            if ":" in ln:
                keypart, val = ln.split(":", 1)
                name = keypart.split(";", 1)[0].upper()
                cur[name] = val

    report["fetched"] = 1
    report["parsed"] = parsed
    return {"rows": rows, "report": report}


def try_ics_fallback(source_name: str, page_url: str, tzname: str) -> Dict[str, Any]:
    ics_url = make_ics_url_from_events_list_url(page_url)
    try:
        txt, status, hdrs = get_text(ics_url, headers={"Accept": "text/calendar,*/*"})
        return ingest_ics_text(source_name, txt, tzname)
    except Exception as e:
        return {"rows": [], "report": {"name": source_name, "url": ics_url, "error": repr(e)}}


# -----------------------
# Sources loader
# -----------------------
@dataclass
class SourceCfg:
    name: str
    kind: str
    url: str
    tz: str
    ics_fallback: bool
    default_duration_minutes: int


def load_sources(path: str = "sources.yaml") -> Tuple[List[SourceCfg], Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    defaults = data.get("defaults", {})
    out: List[SourceCfg] = []
    for s in data.get("sources", []):
        out.append(
            SourceCfg(
                name=s["name"],
                kind=s["kind"],
                url=s["url"],
                tz=s.get("tz") or defaults.get("tz") or "America/Chicago",
                ics_fallback=s.get("ics_fallback", defaults.get("ics_fallback", True)),
                default_duration_minutes=int(s.get("default_duration_minutes", defaults.get("default_duration_minutes", 120))),
            )
        )
    return out, defaults


# -----------------------
# ICS writer
# -----------------------
def write_ics(items: List[Normalized], path: str = OUT_ICS):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//northwoods-events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for i, ev in enumerate(items):
        uid = f"{abs(hash((ev.title, ev.start, ev.url)))}@northwoods-events"
        def fmt(dt_iso: str) -> str:
            # Use local time (floating) to avoid TZ conversion surprises in viewers
            dt = datetime.fromisoformat(dt_iso)
            return dt.strftime("%Y%m%dT%H%M%S")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"SUMMARY:{ev.title}",
            f"DTSTART:{fmt(ev.start)}",
            f"DTEND:{fmt(ev.end)}",
            f"DESCRIPTION:{ev.url}",
        ]
        if ev.location:
            lines.append(f"LOCATION:{ev.location}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# -----------------------
# Main
# -----------------------
def main():
    ensure_dirs()
    sources, defaults = load_sources("sources.yaml")

    all_norm: List[Normalized] = []
    run_report: Dict[str, Any] = {
        "when": now_iso(),
        "timezone": "America/Chicago",
        "sources": [],
    }

    for cfg in sources:
        rows: List[Row] = []
        report: Dict[str, Any] = {"name": cfg.name, "url": cfg.url}
        try:
            if cfg.kind == "modern_tribe":
                res = parse_modern_tribe(cfg.name, cfg.url, cfg.tz)
                rows.extend(res["rows"])
                report.update(res["report"])
                # ICS fallback if nothing parsed
                if cfg.ics_fallback and not rows:
                    ics_res = try_ics_fallback(f"{cfg.name} (ICS)", cfg.url, cfg.tz)
                    rows.extend(ics_res["rows"])
                    # Attach ICS subreport fields for visibility
                    for k, v in ics_res["report"].items():
                        report.setdefault(f"ics_{k}", v)

            elif cfg.kind == "growthzone":
                res = parse_growthzone(cfg.name, cfg.url, cfg.tz)
                rows.extend(res["rows"])
                report.update(res["report"])

            elif cfg.kind == "municipal_calendar":
                res = parse_municipal_calendar(cfg.name, cfg.url, cfg.tz)
                rows.extend(res["rows"])
                report.update(res["report"])
                # ICS fallback (some WP calendars expose ?ical=1)
                if cfg.ics_fallback and not rows:
                    ics_res = try_ics_fallback(f"{cfg.name} (ICS)", cfg.url, cfg.tz)
                    rows.extend(ics_res["rows"])
                    for k, v in ics_res["report"].items():
                        report.setdefault(f"ics_{k}", v)

            # Normalize
            normalized = normalize_rows(rows, default_duration_minutes=cfg.default_duration_minutes)

            # Track quick samples for the report
            samples = []
            for n in normalized[:3]:
                samples.append({
                    "title": n.title,
                    "start": n.start,
                    "location": n.location,
                    "url": n.url,
                })

            report["added"] = len(normalized)
            report["samples"] = samples
            run_report["sources"].append(report)

            all_norm.extend(normalized)

        except Exception as e:
            # Capture any unhandled exception per source but continue
            report["error"] = repr(e)
            run_report["sources"].append(report)

        # be nice to hosts
        time.sleep(1.0)

    # Dedupe across sources
    all_norm = dedupe_events(all_norm)

    # Write ICS and report
    write_ics(all_norm, OUT_ICS)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(run_report, f, indent=2)

    print(f"Wrote {len(all_norm)} events to {OUT_ICS}")
    print(f"Wrote report to {OUT_JSON}")


if __name__ == "__main__":
    main()
