#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unified event scraper runner.

- Looks for sources.{yaml|yml} in repo root, then src/, then current dir.
- Parsers supported:
    - modern_tribe_html
    - growthzone_month
    - squarespace_eventlist
    - simpleview
    - ics

Writes:
- state/snapshots/<slug>.html (raw fetch)
- last_run_report.json (summary)

Requires: requests, beautifulsoup4, lxml, pyyaml, python-dateutil, pytz
"""

from __future__ import annotations
import os, sys, re, json, time, math, logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from dateutil import parser as duparser
import pytz
import yaml

# If normalize.py exists next to us, make it importable
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
try:
    from normalize import parse_datetime_range, clean_text  # your existing helpers
except Exception:
    # Minimal fallbacks if normalize is missing
    def clean_text(s: Optional[str]) -> str:
        if not s: return ""
        s = re.sub(r"\s+", " ", s.strip()).replace("\u200b", "")
        return s
    def parse_datetime_range(date_text=None, iso_hint=None, iso_end_hint=None, tzname="America/Chicago"):
        tz = pytz.timezone(tzname or "America/Chicago")
        # ISO wins
        if iso_hint:
            start = duparser.isoparse(iso_hint)
            if start.tzinfo is None: start = tz.localize(start)
            if iso_end_hint:
                end = duparser.isoparse(iso_end_hint)
                if end.tzinfo is None: end = tz.localize(end)
            else:
                end = start + timedelta(hours=2)
            return start, end, False
        # naive fallback: all-day today
        now = datetime.now(tz)
        start = tz.localize(datetime(now.year, now.month, now.day, 0, 0, 0))
        return start, start + timedelta(days=1) - timedelta(seconds=1), True


CENTRAL_TZNAME = "America/Chicago"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0; +https://example.invalid)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def ensure_dirs():
    os.makedirs("state/snapshots", exist_ok=True)
    os.makedirs("state", exist_ok=True)

def find_sources_path(explicit: Optional[str]) -> str:
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates.extend([
        "sources.yaml", "sources.yml",
        os.path.join("src", "sources.yaml"), os.path.join("src", "sources.yml"),
        os.path.join(THIS_DIR, "sources.yaml"), os.path.join(THIS_DIR, "sources.yml"),
    ])
    for p in candidates:
        if os.path.isfile(p):
            return p
    # last chance: error
    raise FileNotFoundError("Could not find sources.yaml/yml (looked in repo root and src/).")

@dataclass
class Source:
    name: str
    url: str
    kind: str
    enabled: bool = True
    notes: str = ""
    default_duration_minutes: int = 120
    tzname: str = CENTRAL_TZNAME
    # for parsers that may need list vs details
    list_url: Optional[str] = None
    ics_url: Optional[str] = None
    max_detail_visits: int = 20

@dataclass
class EventRow:
    title: str
    url: str
    date_text: str = ""
    iso_hint: Optional[str] = None
    iso_end_hint: Optional[str] = None
    location: str = ""
    all_day: bool = False

def http_get(url: str, *, allow_redirects=True, headers=None, timeout=30) -> requests.Response:
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    r = requests.get(url, headers=h, allow_redirects=allow_redirects, timeout=timeout)
    return r

def write_snapshot(slug: str, text: str, suffix: str = ".html"):
    ensure_dirs()
    path = f"state/snapshots/{slug}{suffix}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path

def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s

# ------------------------
# Parsers
# ------------------------

def parse_modern_tribe_html(base_url: str, html: str) -> List[EventRow]:
    """
    Generic The Events Calendar (Modern Tribe) HTML list parser.
    Handles both Legacy and TEC v6 selectors where possible.
    """
    soup = BeautifulSoup(html, "lxml")

    rows: List[EventRow] = []

    # Try several structures:
    # v1/v2 list card
    cards = soup.select("article.tribe-events-calendar-list__event, div.tribe-events-calendar-list__event")
    if not cards:
        # older or different list markup
        cards = soup.select("div.type-tribe_events, article.type-tribe_events, div.tribe_common--event")
    if not cards:
        # sometimes grid/day list still has schema
        cards = soup.select("[data-event] article, .tribe-events-calendar-day__event")
    for c in cards:
        # title
        a = c.select_one("a.tribe-events-calendar-list__event-title-link, a.tribe-events-pro-photo__event-title-link, h3 a, h2 a, .tribe-event-url")
        title = clean_text(a.get_text()) if a else clean_text(c.select_one("h3, h2").get_text() if c.select_one("h3, h2") else "")
        href = a.get("href") if a and a.has_attr("href") else base_url

        # datetime: prefer machine-readable <time datetime=...>
        t_start = c.select_one("time[datetime].tribe-events-calendar-list__event-datetime-start, time[datetime].tribe-events-pro-photo__event-datetime-start, time[datetime].tribe-event-date-start, time[datetime]")
        t_end = c.select_one("time[datetime].tribe-events-calendar-list__event-datetime-end, time[datetime].tribe-events-pro-photo__event-datetime-end, time[datetime].tribe-event-date-end")

        iso_start = t_start.get("datetime") if t_start else None
        iso_end = t_end.get("datetime") if t_end else None

        # fallback: any visible date text node nearby
        date_text = ""
        if not iso_start:
            dt_el = c.select_one(".tribe-events-calendar-list__event-datetime, .tribe-event-date-start, .tribe-event-date")
            if dt_el:
                date_text = clean_text(dt_el.get_text())

        # location
        loc = ""
        loc_el = c.select_one(".tribe-events-calendar-list__event-venue, .tribe-events-venue-details, .tribe-venue a, .tribe-venue, .tribe-events-venue")
        if loc_el:
            loc = clean_text(loc_el.get_text())

        rows.append(EventRow(title=title or "(untitled)", url=href, date_text=date_text, iso_hint=iso_start, iso_end_hint=iso_end, location=loc))

    return rows


def parse_growthzone_month(base_url: str, html: str) -> List[EventRow]:
    """
    Parse GrowthZone month grid. The date lives on the day cell link
    (e.g. /events/index/2025-08-01) and events are <li class="mn-cal-event"> anchors.
    """
    soup = BeautifulSoup(html, "lxml")
    out: List[EventRow] = []

    # Every active day cell looks like:
    # <div class="mn-cal-day mn-cal-activedate">
    #   <a href=".../events/index/YYYY-MM-DD">1</a>
    #   <ul>
    #     <li class="mn-cal-event ..."><a href=".../events/details/...">Title</a></li>
    #   </ul>
    # </div>
    for day in soup.select("div.mn-cal-day.mn-cal-activedate"):
        # date from the cell anchor (machine readable)
        day_a = day.find("a", href=True)
        date_iso = None
        if day_a and "/events/index/" in day_a["href"]:
            try:
                date_iso = day_a["href"].rsplit("/events/index/", 1)[-1]
                # normalize to ISO 00:00 local; we pass as iso_hint and keep all-day true
                # We'll form an ISO with midnight to help normalize
                date_iso = f"{date_iso}T00:00:00"
            except Exception:
                date_iso = None

        for li in day.select("ul > li.mn-cal-event"):
            a = li.find("a", href=True)
            title = clean_text(a.get_text()) if a else "(untitled)"
            href = urljoin(base_url, a["href"]) if a else base_url
            out.append(EventRow(title=title, url=href, iso_hint=date_iso, date_text="", location=""))

    return out


def parse_squarespace_eventlist(base_url: str, html: str) -> List[EventRow]:
    """
    Squarespace 'Event List' block.

    Typical structure:
    <article class="eventlist-event">
      <h1 class="eventlist-title"><a>Title</a></h1>
      <ul class="eventlist-meta">
        <li class="eventlist-meta-item">
          <time class="event-date" datetime="YYYY-MM-DD">...</time>
          <time class="event-time-localized-start" datetime="YYYY-MM-DDTHH:MM:SS-05:00">...</time>
          <time class="event-time-localized-end"   datetime="YYYY-MM-DDTHH:MM:SS-05:00">...</time>
    """
    soup = BeautifulSoup(html, "lxml")
    out: List[EventRow] = []

    for art in soup.select("article.eventlist-event"):
        a = art.select_one("h1.eventlist-title a, h2.eventlist-title a, .eventlist-title a")
        title = clean_text(a.get_text()) if a else clean_text(art.select_one(".eventlist-title").get_text() if art.select_one(".eventlist-title") else "")
        href = urljoin(base_url, a.get("href")) if a and a.has_attr("href") else base_url

        # time hints
        t_date = art.select_one("time.event-date[datetime]")
        t_start = art.select_one("time.event-time-localized-start[datetime]")
        t_end = art.select_one("time.event-time-localized-end[datetime]")

        iso_start = t_start.get("datetime") if t_start else (t_date.get("datetime") + "T00:00:00" if t_date else None)
        iso_end = t_end.get("datetime") if t_end else None

        # location (often hidden/empty on list; keep empty)
        out.append(EventRow(title=title or "(untitled)", url=href, iso_hint=iso_start, iso_end_hint=iso_end, date_text=""))

    return out


def parse_simpleview(base_url: str, html: str, *, detail_limit:int=20) -> List[EventRow]:
    """
    Lightweight Simpleview fallback:
    - On list pages, Simpleview often renders events via JS. We can't rely on list markup.
    - Strategy: harvest candidate event detail links ("/event/" or "/events/details")
      from the html we do have and visit a limited number of them to extract JSON-LD.
    """
    soup = BeautifulSoup(html, "lxml")
    anchors = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ("/event/" in href) or ("/events/detail" in href) or ("/events/details" in href):
            anchors.append(urljoin(base_url, href))
    # dedupe
    seen = set()
    detail_links = []
    for u in anchors:
        if u not in seen:
            seen.add(u)
            detail_links.append(u)
        if len(detail_links) >= detail_limit:
            break

    rows: List[EventRow] = []
    for u in detail_links:
        try:
            r = http_get(u)
            if r.status_code != 200: 
                continue
            # try JSON-LD
            ld_rows = extract_events_from_jsonld(u, r.text)
            if ld_rows:
                rows.extend(ld_rows)
                continue
            # weak fallback: title only
            soup2 = BeautifulSoup(r.text, "lxml")
            title = clean_text(soup2.select_one("h1, h2").get_text() if soup2.select_one("h1, h2") else "")
            if title:
                rows.append(EventRow(title=title, url=u, date_text=""))
        except Exception:
            continue

    return rows


def extract_events_from_jsonld(page_url: str, html: str) -> List[EventRow]:
    """Find script[type=application/ld+json] Event objects."""
    out: List[EventRow] = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        blob = m.group(1).strip()
        try:
            data = json.loads(blob)
        except Exception:
            continue
        def to_list(x):
            if x is None: return []
            return x if isinstance(x, list) else [x]
        for obj in to_list(data):
            if isinstance(obj, dict) and obj.get("@type") in ("Event", ["Event"]):
                title = clean_text(obj.get("name") or "(untitled)")
                start = obj.get("startDate")
                end = obj.get("endDate")
                loc = ""
                location = obj.get("location")
                if isinstance(location, dict):
                    loc = clean_text(location.get("name") or "")
                out.append(EventRow(title=title, url=page_url, iso_hint=start, iso_end_hint=end, location=loc))
    return out


def parse_ics(url: str) -> List[EventRow]:
    """
    Fetch ICS, verify content-type or content head, then parse via a quick
    regex pull for DTSTART/DTEND/SUMMARY (keep robust but simple here).
    """
    r = http_get(url, headers={"Accept": "text/calendar"})
    text = r.text or ""
    head = text.strip().splitlines()[:5]
    looks_ics = (r.headers.get("Content-Type", "").startswith("text/calendar")) or any("BEGIN:VCALENDAR" in line for line in head)
    if not looks_ics:
        raise RuntimeError("ICS endpoint returned non-ICS (likely HTML/blocked)")
    # Lightweight parse
    rows: List[EventRow] = []
    blocks = re.split(r"(?=BEGIN:VEVENT)", text)
    for b in blocks:
        if "BEGIN:VEVENT" not in b:
            continue
        summary = "(untitled)"
        dtstart = None
        dtend = None
        m = re.search(r"SUMMARY:(.+)", b)
        if m:
            summary = clean_text(m.group(1))
        ms = re.search(r"DTSTART(?:;[^:]+)?:([0-9TzZ+-]+)", b, re.I)
        me = re.search(r"DTEND(?:;[^:]+)?:([0-9TzZ+-]+)", b, re.I)
        if ms:
            dtstart = ms.group(1)
        if me:
            dtend = me.group(1)
        rows.append(EventRow(title=summary, url=url, iso_hint=dtstart, iso_end_hint=dtend))
    return rows

# ------------------------
# Pipeline
# ------------------------

def load_sources(path: Optional[str]) -> Tuple[List[Source], Dict]:
    src_path = find_sources_path(path)
    with open(src_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    defaults = data.get("_defaults", {}) or {}
    out = []
    for item in data.get("sources", []):
        if not item: 
            continue
        if not item.get("enabled", True):
            continue
        out.append(Source(
            name=item["name"],
            url=item["url"],
            kind=item["kind"],
            enabled=item.get("enabled", True),
            notes=item.get("notes", ""),
            default_duration_minutes=item.get("default_duration_minutes", defaults.get("default_duration_minutes", 120)),
            tzname=item.get("tzname", defaults.get("tzname", CENTRAL_TZNAME)),
            list_url=item.get("list_url"),
            ics_url=item.get("ics_url"),
            max_detail_visits=item.get("max_detail_visits", 20),
        ))
    return out, defaults


def normalize_rows(rows: List[EventRow], tzname: str, default_duration_minutes: int) -> List[Dict]:
    out = []
    for r in rows:
        start_dt, end_dt, all_day = parse_datetime_range(
            date_text=r.date_text,
            iso_hint=r.iso_hint,
            iso_end_hint=r.iso_end_hint,
            tzname=tzname,
        )
        if not r.iso_end_hint and not r.date_text and not all_day:
            # give a default duration when we only had start ISO
            end_dt = start_dt + timedelta(minutes=default_duration_minutes)
        out.append({
            "title": clean_text(r.title) or "(untitled)",
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "all_day": all_day,
            "location": clean_text(r.location or ""),
            "url": r.url,
        })
    return out


def run_source(s: Source) -> Dict:
    name_slug = slugify(s.name)
    kind = s.kind.strip().lower()
    base_url = s.url

    fetched = 0
    parsed = 0
    added = 0
    errs = []
    samples = []

    try:
        if kind == "ics":
            rows = parse_ics(s.ics_url or s.url)
            fetched = 1
        else:
            # GET the list page
            r = http_get(s.list_url or s.url)
            fetched = 1
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} for {s.list_url or s.url}")
            snap_path = write_snapshot(f"{name_slug}", r.text)
            # route by kind
            if kind in ("modern_tribe", "modern_tribe_html"):
                rows = parse_modern_tribe_html(base_url, r.text)
            elif kind in ("growthzone", "growthzone_month"):
                rows = parse_growthzone_month(base_url, r.text)
            elif kind in ("squarespace", "squarespace_eventlist"):
                rows = parse_squarespace_eventlist(base_url, r.text)
            elif kind in ("simpleview", "simpleview_fallback"):
                rows = parse_simpleview(base_url, r.text, detail_limit=s.max_detail_visits)
            else:
                raise RuntimeError(f"Unknown kind '{s.kind}'")
        parsed = len(rows)

        normalized = normalize_rows(rows, tzname=s.tzname, default_duration_minutes=s.default_duration_minutes)
        added = len(normalized)
        samples = [
            {"title": ev["title"], "start": ev["start"], "location": ev.get("location",""), "url": ev["url"]}
            for ev in normalized[:3]
        ]
        return {
            "name": s.name,
            "url": s.url,
            "fetched": fetched,
            "parsed": parsed,
            "added": added,
            "samples": samples,
        }
    except Exception as e:
        return {
            "name": s.name,
            "url": s.url,
            "fetched": fetched,
            "parsed": parsed,
            "added": added,
            "samples": samples,
            "error": str(e),
        }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=None, help="Path to sources.yaml/yml (repo root preferred)")
    args = ap.parse_args()

    ensure_dirs()

    sources, defaults = load_sources(args.sources)

    report = {
        "when": datetime.now(pytz.timezone(CENTRAL_TZNAME)).isoformat(),
        "timezone": CENTRAL_TZNAME,
        "sources": [],
    }

    for s in sources:
        info = run_source(s)
        report["sources"].append(info)

    with open("last_run_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # also print a tiny summary for Actions logs
    print("=== SUMMARY ===")
    for s in report["sources"]:
        line = f"{s['name']}: fetched={s.get('fetched',0)} parsed={s.get('parsed',0)} added={s.get('added',0)}"
        if "error" in s:
            line += f" ERROR={s['error']}"
        print(line)


if __name__ == "__main__":
    main()
