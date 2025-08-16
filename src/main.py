import json
import os
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse

import pytz
import yaml
from bs4 import BeautifulSoup  # used only to extract iframes/links in this file

from fetch import get                           # static HTTP fetch -> (html, final_url, status)
from render import render_url                   # headless render -> (html, final_url)
from ics_fetch import get_ics_text              # (kept for future ICS sources)
from parse_modern_tribe import parse as parse_mt
from parse_growthzone import parse as parse_gz
from parse_ics import parse as parse_ics
from normalize import clean_text, parse_datetime_range
from dedupe import stable_id
from icsbuild import build_ics

ROOT = os.path.dirname(os.path.dirname(__file__))
STATE = os.path.join(ROOT, "state", "seen.json")
ICS_OUT = os.path.join(ROOT, "docs", "northwoods.ics")
REPORT = os.path.join(ROOT, "state", "last_run_report.json")
SNAPDIR = os.path.join(ROOT, "state", "snapshots")


def load_yaml():
    with open(os.path.join(ROOT, "src", "sources.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_seen():
    if not os.path.exists(STATE):
        return {}
    with open(STATE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, sort_keys=True)


def absolutize(url, source_url):
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(source_url, url)


def _guess_kind_from_url(url: str) -> str:
    """
    Heuristic: GrowthZone/ChamberMaster usually lives on business.* and /events/* paths.
    """
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    if "business." in host or "chamber" in host or "/events/" in path:
        return "growthzone"
    return "modern_tribe"


def _parse_by_type(kind, html_or_text):
    if kind == "modern_tribe":
        return parse_mt(html_or_text)
    if kind == "growthzone":
        return parse_gz(html_or_text)
    if kind == "ics":
        return parse_ics(html_or_text)
    return []


def _extract_iframe_srcs(html: str, base_url: str):
    """
    Pull absolute iframe src URLs from the HTML, ignoring empty/about:blank.
    """
    out = []
    soup = BeautifulSoup(html or "", "lxml")
    for fr in soup.find_all("iframe"):
        src = (fr.get("src") or "").strip()
        if not src or src.startswith("about:") or src.startswith("data:"):
            continue
        out.append(absolutize(src, base_url))
    return list(dict.fromkeys(out))  # de-dup preserve order


def _slugify(name: str) -> str:
    return (
        name.lower()
        .replace(" ", "_")
        .replace("(", "")
        .replace(")", "")
        .replace("–", "-")
        .replace("—", "-")
        .replace("&", "and")
    )


def main():
    cfg = load_yaml()
    tzname = cfg.get("timezone", "America/Chicago")
    default_minutes = int(cfg.get("default_duration_minutes", 60))
    seen = load_seen()

    tz = pytz.timezone(tzname)
    now = tz.localize(datetime.now())

    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "state"), exist_ok=True)
    os.makedirs(SNAPDIR, exist_ok=True)

    collected = []
    report = {"when": now.isoformat(), "sources": []}

    for s in cfg["sources"]:
        src_report = {
            "name": s["name"], "url": s["url"],
            "fetched": 0, "parsed": 0, "added": 0,
            "skipped_past": 0, "skipped_nodate": 0, "skipped_dupe": 0,
            "samples": []
        }

        try:
            rows = []

            if s["type"] == "ics":
                # Robust ICS fetch (kept for future use)
                fam = s.get("ics_family") or ("growthzone" if "business." in s["url"] else "modern_tribe")
                ics_text = get_ics_text(s["url"], fam)
                rows = _parse_by_type("ics", ics_text)
                src_report["fetched"] = len(rows)

            else:
                # 1) STATIC HTML
                html_static, final_url_static, status = get(s["url"])
                rows = _parse_by_type(s["type"], html_static)

                # Always look for iframes; many WP pages wrap a GrowthZone calendar
                iframe_srcs = _extract_iframe_srcs(html_static, final_url_static)

                # 2) RENDERED HTML if needed
                if not rows:
                    try:
                        wait_sel = s.get("wait_selector")
                        html_dyn, final_url_dyn = render_url(
                            s["url"],
                            wait_selector=wait_sel,
                            timeout_ms=25000
                        )
                        more = _parse_by_type(s["type"], html_dyn)
                        rows.extend(more)

                        # save rendered snapshot
                        slug = _slugify(s["name"])
                        snap_path_dyn = os.path.join(SNAPDIR, f"{slug}.rendered.html")
                        with open(snap_path_dyn, "w", encoding="utf-8") as f:
                            f.write(f"<!-- URL: {s['url']} | Final: {final_url_dyn} (rendered) -->\n")
                            f.write(html_dyn[:300000])
                        src_report["snapshot_rendered"] = os.path.relpath(snap_path_dyn, ROOT)

                        # collect iframes from rendered doc too (sometimes added in JS)
                        iframe_srcs += _extract_iframe_srcs(html_dyn, final_url_dyn)
                        iframe_srcs = list(dict.fromkeys(iframe_srcs))
                    except Exception:
                        pass

                # 3) IF FRAME(S) EXIST, RENDER + PARSE THEM
                frame_rows = []
                for i, fr_url in enumerate(iframe_srcs[:5]):  # safety cap 5 frames
                    try:
                        fr_html, fr_final = render_url(fr_url, wait_selector=None, timeout_ms=25000)
                        kind = _guess_kind_from_url(fr_final)
                        parsed = _parse_by_type(kind, fr_html)
                        frame_rows.extend(parsed)

                        # snapshot frame for debugging
                        slug = _slugify(s["name"])
                        fr_slug = _slugify(urlparse(fr_final).netloc + urlparse(fr_final).path.replace("/", "_"))
                        snap_path_fr = os.path.join(SNAPDIR, f"{slug}.frame{i+1}.{fr_slug}.html")
                        with open(snap_path_fr, "w", encoding="utf-8") as f:
                            f.write(f"<!-- IFRAME: {fr_url} | Final: {fr_final} | Kind: {kind} -->\n")
                            f.write(fr_html[:300000])
                        src_report[f"snapshot_frame_{i+1}"] = os.path.relpath(snap_path_fr, ROOT)
                    except Exception as e:
                        src_report[f"frame_{i+1}_error"] = repr(e)

                rows.extend(frame_rows)

                src_report["fetched"] = len(rows)

                # If still zero, save static snapshot for debugging
                if len(rows) == 0:
                    slug = _slugify(s["name"])
                    snap_path = os.path.join(SNAPDIR, f"{slug}.html")
                    try:
                        with open(snap_path, "w", encoding="utf-8") as f:
                            f.write(f"<!-- URL: {s['url']} | Final: {final_url_static} | Status: {status} -->\n")
                            f.write(html_static[:200000])
                        src_report["snapshot"] = os.path.relpath(snap_path, ROOT)
                    except Exception:
                        pass

            # Post-parse normalization & filtering
            for r in rows:
                title = clean_text(r.get("title"))
                url = absolutize(r.get("url", ""), s["url"])
                location = clean_text(r.get("venue_text") or "")
                date_text = clean_text(r.get("date_text") or "")
                iso_from_attr = r.get("iso_datetime")
                iso_end = r.get("iso_end")

                start, end, all_day = parse_datetime_range(
                    date_text, tzname, default_minutes,
                    iso_hint=iso_from_attr, iso_end_hint=iso_end
                )
                if not start or not end:
                    src_report["skipped_nodate"] += 1
                    if len(src_report["samples"]) < 5:
                        src_report["samples"].append({
                            "reason": "nodate",
                            "title": title,
                            "date_text": date_text,
                            "iso_hint": iso_from_attr
                        })
                    continue

                # Future or today only
                if start.replace(hour=0, minute=0, second=0, microsecond=0) < now.replace(hour=0, minute=0, second=0, microsecond=0):
                    src_report["skipped_past"] += 1
                    if len(src_report["samples"]) < 5:
                        src_report["samples"].append({
                            "reason": "past",
                            "title": title,
                            "start": start.isoformat(),
                            "date_text": date_text
                        })
                    continue

                sid = stable_id(title, start.isoformat(), location, url)
                if sid in seen:
                    src_report["skipped_dupe"] += 1
                    continue

                collected.append({
                    "title": title,
                    "description": "",
                    "location": location,
                    "url": url,
                    "start": start,
                    "end": end,
                    "all_day": all_day,
                    "sid": sid
                })
                seen[sid] = {"added": now.isoformat(), "source": s["name"]}
                src_report["added"] += 1
                src_report["parsed"] += 1

        except Exception as e:
            src_report["error"] = repr(e)

        report["sources"].append(src_report)

    # Build ICS
    build_ics(collected, ICS_OUT)

    # Persist state + report
    save_seen(seen)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Print a short summary for Actions logs
    total_added = sum(s["added"] for s in report["sources"])
    summary = {
        "total_added": total_added,
        "per_source": [
            {
                "name": s["name"],
                "fetched": s["fetched"],
                "parsed": s["parsed"],
                "added": s["added"],
                "skipped_past": s["skipped_past"],
                "skipped_nodate": s["skipped_nodate"],
                "skipped_dupe": s["skipped_dupe"],
                **({"snapshot": s.get("snapshot")} if s.get("snapshot") else {}),
                **({"snapshot_rendered": s.get("snapshot_rendered")} if s.get("snapshot_rendered") else {}),
                **({k: s[k] for k in s.keys() if k.startswith("snapshot_frame_")} if any(k.startswith("snapshot_frame_") for k in s.keys()) else {}),
                **({k: s[k] for k in s.keys() if k.startswith("frame_") and k.endswith("_error")} if any(k.startswith("frame_") and k.endswith("_error") for k in s.keys()) else {}),
                **({"error": s.get("error")} if s.get("error") else {}),
            }
            for s in report["sources"]
        ]
    }
    print("SUMMARY:", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
