#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparse
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event as ICalEvent
import yaml
import feedparser

# ---------------------------------
# Constants & HTTP session
# ---------------------------------

CENTRAL = ZoneInfo("America/Chicago")

DEFAULT_SOURCES = {
    "minocqua": {
        "type": "rss_jsonld",
        "rss": "https://www.minocqua.org/event/rss/",
        "homepage": "https://www.minocqua.org/events/"
    },
    "vilas": {
        "type": "ics_auto",
        "page": "https://vilaswi.com/events/"
    },
    "oneida": {
        "type": "ics_or_html",
        "page": "https://oneidacountywi.com/festivals-events/"
    },
    "st_germain": {
        "type": "ics_auto",
        "page": "https://stgermainwi.chambermaster.com/events/calendarcatgid/3"
    },
    "manitowish_waters": {
        "type": "html_jsonld",
        "page": "https://manitowishwaters.org/events/"
    }
}

HEADERS = {
    "User-Agent": "NorthwoodsEventsBot/1.0 (+https://example.org; contact: maintainer@example.org)"
}

SESS = requests.Session()
ADAPTER = requests.adapters.HTTPAdapter(max_retries=3)
SESS.mount("http://", ADAPTER)
SESS.mount("https://", ADAPTER)
SESS.headers.update(HEADERS)

# ---------------------------------
# Model & helpers
# ---------------------------------

@dataclass
class EventItem:
    source: str
    source_event_id: str
    title: str
    start: datetime
    end: Optional[datetime]
    tz: str
    location_name: Optional[str]
    location_address: Optional[str]
    city: Optional[str]
    url: Optional[str]
    description: Optional[str]

    def dedup_key(self) -> Tuple[str, str, str]:
        return (
            normalize_title(self.title),
            self.start.astimezone(CENTRAL).strftime("%Y-%m-%d"),
            normalize_place(self.location_name or self.city or self.location_address or "")
        )

def normalize_title(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[\W_]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s

def normalize_place(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

def strip_html(s: str) -> str:
    return re.sub("<[^>]+>", "", s or "").strip()

def safe_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CENTRAL)
    if isinstance(value, date):
        # All-day date; interpret as midnight local time
        return datetime(value.year, value.month, value.day, tzinfo=CENTRAL)
    try:
        dt = dateparse.parse(str(value))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=CENTRAL)
        return dt
    except Exception:
        return None

def ensure_tz(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=CENTRAL)

def make_uid(ev: EventItem) -> str:
    base = f"{ev.source}|{ev.source_event_id}|{ev.start.astimezone(timezone.utc).isoformat()}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest() + "@northwoods"

# ---------------------------------
# HTTP & parsing helpers
# ---------------------------------

def get(url: str, *, timeout: int = 20) -> requests.Response:
    r = SESS.get(url, timeout=timeout)
    r.raise_for_status()
    return r

def find_ics_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        text = (a.get_text() or "").lower()
        if not href:
            continue
        full = urljoin(base_url, href)
        if "ical" in href.lower() or href.lower().endswith(".ics") or href.lower().startswith("webcal://"):
            links.append(full)
        elif "ics" in text or "ical" in text or "export" in text:
            links.append(full)
    uniq = []
    seen = set()
    for u in links:
        if u not in seen:
            uniq.append(u)
            seen.add(u)
    return uniq

def parse_jsonld_events(html: str, page_url: str) -> List[EventItem]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select('script[type="application/ld+json"]')
    out: List[EventItem] = []
    for b in blocks:
        try:
            data = json.loads(b.string or "{}")
        except Exception:
            continue
        for ev in iter_jsonld_events(data):
            itm = jsonld_to_eventitem(ev, page_url)
            if itm:
                out.append(itm)
    return out

def iter_jsonld_events(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        t = obj.get("@type")
        if t == "Event":
            yield obj
        if "@graph" in obj and isinstance(obj["@graph"], list):
            for it in obj["@graph"]:
                yield from iter_jsonld_events(it)
        if "itemListElement" in obj and isinstance(obj["itemListElement"], list):
            for it in obj["itemListElement"]:
                yield from iter_jsonld_events(it)
    elif isinstance(obj, list):
        for it in obj:
            yield from iter_jsonld_events(it)

def jsonld_to_eventitem(ev: Dict[str, Any], page_url: str) -> Optional[EventItem]:
    title = (ev.get("name") or ev.get("headline") or "").strip()
    start = safe_dt(ev.get("startDate"))
    end = safe_dt(ev.get("endDate"))
    url = ev.get("url") or page_url

    loc = ev.get("location")
    location_name = None
    location_address = None
    city = None
    if isinstance(loc, dict):
        location_name = (loc.get("name") or None)
        addr = loc.get("address")
        if isinstance(addr, dict):
            location_address = " ".join([
                addr.get("streetAddress") or "",
                addr.get("addressLocality") or "",
                addr.get("addressRegion") or "",
                addr.get("postalCode") or ""
            ]).strip() or None
            city = addr.get("addressLocality") or None
        elif isinstance(addr, str):
            location_address = addr or None

    if not title or not start:
        return None

    return EventItem(
        source="jsonld",
        source_event_id=url or title,
        title=title,
        start=ensure_tz(start) or datetime.now(tz=CENTRAL),
        end=ensure_tz(end),
        tz="America/Chicago",
        location_name=location_name,
        location_address=location_address,
        city=city,
        url=url,
        description=strip_html(ev.get("description") or "")
    )

# ---------------------------------
# Source adapters
# ---------------------------------

def ingest_ics(urls: List[str], source_id: str) -> Tuple[List[EventItem], List[str]]:
    events: List[EventItem] = []
    logs: List[str] = []
    for u in urls:
        try:
            if u.startswith("webcal://"):
                u = "https://" + u[len("webcal://"):]
            r = get(u)
            cal = Calendar.from_ical(r.content)
            count_before = len(events)
            for comp in cal.walk():
                if comp.name != "VEVENT":
                    continue
                title = str(comp.get("summary") or "").strip()
                if not title:
                    continue

                dtstart = comp.get("dtstart")
                dtend = comp.get("dtend")

                start_raw = dtstart.dt if hasattr(dtstart, "dt") else None
                end_raw = dtend.dt if hasattr(dtend, "dt") else None

                start = safe_dt(start_raw)
                end = safe_dt(end_raw)

                loc = str(comp.get("location") or "").strip() or None
                url = str(comp.get("url") or "").strip() or None
                desc = str(comp.get("description") or "").strip() or None

                events.append(EventItem(
                    source=source_id,
                    source_event_id=str(comp.get("uid") or url or title),
                    title=title,
                    start=start or datetime.now(tz=CENTRAL),
                    end=end,
                    tz="America/Chicago",
                    location_name=loc,
                    location_address=None,
                    city=None,
                    url=url,
                    description=desc
                ))
            logs.append(f"{source_id}: parsed {len(events)-count_before} from {u}")
        except Exception as e:
            logs.append(f"{source_id}: failed {u} -> {e}")
    return events, logs

def discover_ics_from_page(page_url: str) -> List[str]:
    try:
        html = get(page_url).text
        links = find_ics_links(html, page_url)
        if not links:
            base = page_url.rstrip("/")
            guesses = [
                base + "/?ical=1",
                base + "/month/?ical=1",
                base.replace("/festivals-events", "/events") + "/?ical=1",
                base.replace("/events-calendar", "/events") + "/?ical=1",
            ]
            links.extend(guesses)
        seen = set()
        out = []
        for u in links:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out
    except Exception:
        return []

def ingest_rss_jsonld(rss_url: str, source_id: str, limit: int = 200) -> Tuple[List[EventItem], List[str]]:
    logs: List[str] = []
    out: List[EventItem] = []
    try:
        feed = feedparser.parse(rss_url)
        entries = feed.entries[:limit]
        logs.append(f"{source_id}: RSS entries={len(entries)}")
        for e in entries:
            link = e.get("link")
            if not link:
                continue
            try:
                html = get(link).text
                evs = parse_jsonld_events(html, link)
                if evs:
                    for ev in evs:
                        ev.source = source_id
                        ev.source_event_id = ev.url or ev.title
                    out.extend(evs)
                else:
                    title = e.get("title") or e.get("summary") or "Untitled"
                    start = safe_dt(
                        e.get("published")
                        or e.get("updated")
                        or e.get("pubDate")
                    )
                    if start:
                        out.append(EventItem(
                            source=source_id,
                            source_event_id=link,
                            title=title,
                            start=ensure_tz(start),
                            end=None,
                            tz="America/Chicago",
                            location_name=None,
                            location_address=None,
                            city=None,
                            url=link,
                            description=strip_html(e.get("summary") or "")
                        ))
            except Exception as ex:
                logs.append(f"{source_id}: detail fetch failed {link} -> {ex}")
            time.sleep(0.5)
    except Exception as e:
        logs.append(f"{source_id}: RSS failed {rss_url} -> {e}")
    return out, logs

def ingest_html_jsonld(listing_url: str, source_id: str) -> Tuple[List[EventItem], List[str]]:
    logs: List[str] = []
    out: List[EventItem] = []
    try:
        html = get(listing_url).text
        soup = BeautifulSoup(html, "html.parser")
        detail_hrefs = set()
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            full = urljoin(listing_url, href)
            p = urlparse(full)
            if any(k in full.lower() for k in ["/event", "/events/", "calendar", "whatson"]):
                if p.netloc == urlparse(listing_url).netloc:
                    detail_hrefs.add(full)
        detail_links = list(detail_hrefs)[:100]
        logs.append(f"{source_id}: candidate detail links={len(detail_links)}")
        for link in detail_links:
            try:
                detail_html = get(link).text
                evs = parse_jsonld_events(detail_html, link)
                for ev in evs:
                    ev.source = source_id
                    ev.source_event_id = ev.url or ev.title
                out.extend(evs)
            except Exception as ex:
                logs.append(f"{source_id}: detail fetch failed {link} -> {ex}")
            time.sleep(0.5)
    except Exception as e:
        logs.append(f"{source_id}: listing fetch failed {listing_url} -> {e}")
    return out, logs

# ---------------------------------
# Orchestration
# ---------------------------------

def load_sources(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if path and path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("sources") or DEFAULT_SOURCES
    return DEFAULT_SOURCES

def deduplicate(items: List[EventItem]) -> Tuple[List[EventItem], List[str], Dict[str, Any]]:
    logs: List[str] = []
    seen: Dict[Tuple[str, str, str], EventItem] = {}
    collisions = 0
    for ev in items:
        key = ev.dedup_key()
        if key not in seen:
            seen[key] = ev
        else:
            incumbent = seen[key]
            score_new = (1 if ev.url else 0) + (1 if ev.end else 0) + (1 if (ev.description and len(ev.description) > 80) else 0)
            score_old = (1 if incumbent.url else 0) + (1 if incumbent.end else 0) + (1 if (incumbent.description and len(incumbent.description) > 80) else 0)
            if score_new > score_old:
                seen[key] = ev
            collisions += 1
    out = list(seen.values())
    stats = {"collisions": collisions, "unique": len(out)}
    return out, logs, stats

def write_ics(events: List[EventItem], out_path: Path) -> None:
    cal = Calendar()
    cal.add("prodid", "-//Northwoods Events//EN")
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", "Northwoods Events")
    cal.add("X-WR-TIMEZONE", "America/Chicago")

    for ev in events:
        ie = ICalEvent()
        ie.add("uid", make_uid(ev))
        ie.add("summary", ev.title)
        ie.add("dtstart", ev.start.astimezone(CENTRAL))
        if ev.end:
            ie.add("dtend", ev.end.astimezone(CENTRAL))
        if ev.description:
            ie.add("description", ev.description)
        if ev.url:
            ie.add("url", ev.url)

        loc = ev.location_name or ""
        if ev.city and (ev.city.lower() not in (loc.lower() if loc else "")):
            loc = (loc + ", " if loc else "") + ev.city
        if ev.location_address:
            loc = (loc + " — " if loc else "") + ev.location_address
        if loc:
            ie.add("location", loc)

        cal.add_component(ie)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(cal.to_ical())

def write_report(report: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

def run_pipeline(sources: Dict[str, Dict[str, Any]]) -> Tuple[List[EventItem], Dict[str, Any]]:
    all_events: List[EventItem] = []
    logs: List[str] = []
    per_source_counts: Dict[str, int] = {}
    for sid, cfg in sources.items():
        t = cfg.get("type")
        try:
            if t == "ics_auto":
                page = cfg["page"]
                ics_links = cfg.get("ics") or discover_ics_from_page(page)
                evs, l = ingest_ics(ics_links, sid)
            elif t == "ics_or_html":
                page = cfg["page"]
                ics_links = cfg.get("ics") or discover_ics_from_page(page)
                if ics_links:
                    evs, l = ingest_ics(ics_links, sid)
                else:
                    evs, l = ingest_html_jsonld(page, sid)
            elif t == "rss_jsonld":
                rss = cfg["rss"]
                evs, l = ingest_rss_jsonld(rss, sid)
            elif t == "html_jsonld":
                page = cfg["page"]
                evs, l = ingest_html_jsonld(page, sid)
            else:
                evs, l = [], [f"{sid}: unknown type {t}"]
        except Exception as e:
            evs, l = [], [f"{sid}: adapter failed -> {e}"]
        logs.extend(l)
        per_source_counts[sid] = len(evs)
        all_events.extend(evs)

    deduped, dlogs, dedup_stats = deduplicate(all_events)
    logs.extend(dlogs)

    report = {
        "timestamp": datetime.now(tz=CENTRAL).isoformat(),
        "per_source_counts": per_source_counts,
        "total_raw": len(all_events),
        "total_deduped": len(deduped),
        "dedup_stats": dedup_stats,
        "logs": logs[-500:]
    }
    return deduped, report

def main() -> int:
    ap = argparse.ArgumentParser(description="Aggregate tourism events into a single ICS.")
    ap.add_argument("--sources", type=Path, default=Path("sources.yaml"), help="Optional YAML config.")
    ap.add_argument("--out", type=Path, default=Path("build/events.ics"), help="Output ICS file.")
    ap.add_argument("--report", type=Path, default=Path("build/last_run_report.json"), help="Diagnostics report.")
    args = ap.parse_args()

    sources = load_sources(args.sources if args.sources.exists() else None)
    events, report = run_pipeline(sources)
    write_ics(events, args.out)
    write_report(report, args.report)

    print(f"Wrote {len(events)} events -> {args.out}")
    print(f"Report -> {args.report}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
