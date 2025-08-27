#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
import requests
import yaml
from bs4 import BeautifulSoup

# ====== normalize helpers ======
try:
    from normalize import parse_datetime_range, clean_text  # type: ignore
except Exception:
    def clean_text(s: Optional[str]) -> str:
        if not s:
            return ""
        s = re.sub(r"\s+", " ", s.strip())
        return s.replace("\u200b", "")

    def parse_datetime_range(*args, **kwargs):
        tzname = kwargs.get("tzname") or "America/Chicago"
        tz = pytz.timezone(tzname)
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


# ====== FS helpers ======
def ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(SNAP_DIR, exist_ok=True)


def now_iso() -> str:
    return datetime.now(CENTRAL).isoformat()


def save_snapshot(name: str, content: str, rendered: bool = False) -> str:
    safe = re.sub(r"[^a-z0-9._\\-() ]+", "_", name.lower())
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


# ====== path resolution for sources.{yml,yaml} ======
def resolve_sources_path(cli_path: Optional[str] = None) -> str:
    """
    Find a config file to load. Resolution order:

    1) --config PATH (CLI) if provided and exists
    2) $SOURCES_PATH (env) if provided and exists
    3) ./sources.yaml
    4) ./sources.yml
    5) <repo-root>/sources.yaml           # repo-root = parent of this file's dir
    6) <repo-root>/sources.yml

    If none found, raise FileNotFoundError listing tried paths.
    """
    tried: List[str] = []

    def existing(p: Optional[str]) -> Optional[str]:
        if p and os.path.isfile(p):
            return p
        if p:
            tried.append(os.path.abspath(p))
        return None

    # 1) CLI
    if existing(cli_path):
        return cli_path  # type: ignore

    # 2) env
    env_path = os.environ.get("SOURCES_PATH")
    if existing(env_path):
        return env_path  # type: ignore

    # 3) & 4) CWD
    for name in ("sources.yaml", "sources.yml"):
        p = os.path.join(os.getcwd(), name)
        if existing(p):
            return p  # type: ignore

    # 5) & 6) repo root (parent of src/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, ".."))
    for name in ("sources.yaml", "sources.yml"):
        p = os.path.join(repo_root, name)
        if existing(p):
            return p  # type: ignore

    raise FileNotFoundError(
        "Could not find sources config. Tried:\n  - " + "\n  - ".join(tried) +
        "\nYou can also set --config PATH or SOURCES_PATH."
    )


# ====== normalizing ======
def to_local(dt: datetime, tzname: str) -> datetime:
    tz = pytz.timezone(tzname or "America/Chicago")
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt.astimezone(tz)


def normalize_rows(rows: List[Row], default_duration_minutes: int = 120) -> List[Normalized]:
    out: List[Normalized] = []
    for r in rows:
        try:
            start_dt, end_dt, all_day = parse_datetime_range(
                date_text=r.date_text,
                iso_hint=r.iso_hint,
                iso_end_hint=r.iso_end_hint,
                tzname=r.tzname or "America/Chicago",
            )
        except TypeError:
            try:
                start_dt, end_dt, all_day = parse_datetime_range(r.date_text, r.iso_hint, r.iso_end_hint)
            except Exception:
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
        key = (it.title.lower().strip(), it.start[:10])
        if key not in seen:
            keep.append(it)
            seen.add(key)
    return keep


# ====== tribe / growthzone / municipal parsers ======
def make_ics_url_from_events_list_url(url: str) -> str:
    base = url.split("?")[0] if "?" in url else url
    return f"{base}?ical=1"


def tribe_rest_root(url: str) -> str:
    m = re.match(r"^(https?://[^/]+)/", url)
    if not m:
        return ""
    root = m.group(1)
    return root + "/wp-json/tribe/events/v1/events"


def parse_modern_tribe(source_name: str, url: str, tzname: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {"name": source_name, "url": url, "fetched": 0, "parsed": 0}
    rows: List[Row] = []

    # 1) REST
    try:
        api = tribe_rest_root(url)
        if api:
            params = {
                "page": 1,
                "per_page": 100,
                "start_date": (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z",
                "end_date": (datetime.utcnow() + timedelta(days=365)).isoformat() + "Z",
            }
            page = 1
            total = 0
            while True:
                r = requests.get(api, params=params, headers={"Accept": "application/json", **HEADERS}, timeout=REQ_TIMEOUT)
                status = r.status_code
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
                params["page"] = page
                if page > 10:
                    break
            if total > 0:
                report["fetched"] = 1
                report["parsed"] = total
                return {"rows": rows, "report": report}
    except Exception as e:
        report["rest_error"] = repr(e)

    # 2) HTML scrape
    try:
        txt, status, hdrs = get_text(url)
        report["fetched"] = 1
        save_snapshot(f"{source_name}", txt, rendered=False)
        soup = BeautifulSoup(txt, "lxml")
        articles = soup.select("article.type-tribe_events, article.tribe_events")
        if not articles:
            articles = soup.select("[data-tribe-event-id], .tribe-common-c-card")
        for art in articles:
            a = art.select_one("a.tribe-event-url, a.url, a[href*='/event/']")
            if not a:
                continue
            link = a.get("href") or url
            title = clean_text(a.get_text())
            time_tag = art.select_one("time[itemprop='startDate'], time.tribe-event-date-start")
            date_text = ""
            iso = ""
            if time_tag:
                iso = (time_tag.get("datetime") or "").strip()
                if not iso:
                    date_text = clean_text(time_tag.get_text())
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

    return {"rows": [], "report": report}


def parse_growthzone(source_name: str, url: str, tzname: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {"name": source_name, "url": url, "fetched": 0, "parsed": 0}
    rows: List[Row] = []
    try:
        txt, status, hdrs = get_text(url)
        report["fetched"] = 1
        save_snapshot(f"{source_name}", txt)
        soup = BeautifulSoup(txt, "lxml")

        items = soup.select(".gz-event-list-item, .event-listing, .gz-event, .event-item, .item-event")
        if not items:
            items = soup.select("a[href*='/events/details/']")

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

        for href in links[:50]:
            try:
                dtxt, st, hh = get_text(href)
                dsoup = BeautifulSoup(dtxt, "lxml")
                el = dsoup.select_one("h1") or dsoup.select_one(".event-title") or dsoup.title
                title = clean_text(el.get_text()) if el else "(untitled)"
                time_tag = dsoup.select_one("time[datetime]")
                iso = time_tag.get("datetime").strip() if time_tag and time_tag.has_attr("datetime") else ""
                date_text = ""
                if not iso:
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
    report: Dict[str, Any] = {"name": source_name, "url": url, "fetched": 0, "parsed": 0}
    rows: List[Row] = []
    try:
        txt, status, hdrs = get_text(url)
        report["fetched"] = 1
        save_snapshot(f"{source_name}", txt)
        soup = BeautifulSoup(txt, "lxml")

        candidates = soup.select(
            ".calendar a, .events a, .ai1ec-event-title a, a.event, a[href*='/event/'], a[href*='?event']"
        )
        if not candidates:
            candidates = soup.select("li a, .entry-content a")

        for a in candidates:
            href = a.get("href") or url
            title = clean_text(a.get_text()) or "(untitled)"
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


# ====== ICS handling (safe) ======
def ingest_ics_text(source_name: str, ics_text: str, tzname: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {"name": source_name, "fetched": 0, "parsed": 0}
    rows: List[Row] = []

    txt = ics_text.strip()
    if not txt.startswith("BEGIN:VCALENDAR"):
        report["error"] = "ICS endpoint returned non-ICS (likely HTML/blocked)"
        save_snapshot(f"{source_name} (ics) (ics_response)", ics_text)
        return {"rows": [], "report": report}

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
            date_text="",
            iso_hint=dtstart,
            iso_end_hint=dtend,
            location=loc,
            tzname=tzname,
            source=source_name,
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
            if ":" in ln:
                keypart, val = ln.split(":", 1)
                name = keypart.split(";", 1)[0].upper()
                cur[name] = val

    report["fetched"] = 1
    report["parsed"] = parsed
    return {"rows": rows, "report": report}


def try_ics_fallback(source_name: str, page_url: str, tzname: str) -> Dict[str, Any]:
    base = page_url.split("?")[0] if "?" in page_url else page_url
    ics_url = f"{base}?ical=1"
    try:
        txt, status, hdrs = get_text(ics_url, headers={"Accept": "text/calendar,*/*"})
        return ingest_ics_text(source_name, txt, tzname)
    except Exception as e:
        return {"rows": [], "report": {"name": source_name, "url": ics_url, "error": repr(e)}}


# ====== sources loader ======
@dataclass
class SourceCfg:
    name: str
    kind: str
    url: str
    tz: str
    ics_fallback: bool
    default_duration_minutes: int


def load_sources(resolved_path: str) -> Tuple[List[SourceCfg], Dict[str, Any]]:
    with open(resolved_path, "r", encoding="utf-8") as f:
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


# ====== ICS writer ======
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


# ====== main ======
def main(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to sources.{yml,yaml}", default=None)
    args = parser.parse_args(argv)

    ensure_dirs()

    cfg_path = resolve_sources_path(args.config)
    print(f"[info] Using config: {cfg_path}")

    sources, defaults = load_sources(cfg_path)

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
                if cfg.ics_fallback and not rows:
                    ics_res = try_ics_fallback(f"{cfg.name} (ICS)", cfg.url, cfg.tz)
                    rows.extend(ics_res["rows"])
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
                if cfg.ics_fallback and not rows:
                    ics_res = try_ics_fallback(f"{cfg.name} (ICS)", cfg.url, cfg.tz)
                    rows.extend(ics_res["rows"])
                    for k, v in ics_res["report"].items():
                        report.setdefault(f"ics_{k}", v)

            normalized = normalize_rows(rows, default_duration_minutes=cfg.default_duration_minutes)

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
            report["error"] = repr(e)
            run_report["sources"].append(report)

        time.sleep(1.0)

    all_norm = dedupe_events(all_norm)

    write_ics(all_norm, OUT_ICS)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(run_report, f, indent=2)

    print(f"Wrote {len(all_norm)} events to {OUT_ICS}")
    print(f"Wrote report to {OUT_JSON}")


if __name__ == "__main__":
    main()
