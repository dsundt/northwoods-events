import json, os
from datetime import datetime
from urllib.parse import urljoin

import pytz
import yaml

from fetch import get
from parse_modern_tribe import parse as parse_mt
from parse_growthzone import parse as parse_gz
from normalize import clean_text, parse_datetime_range
from dedupe import stable_id
from icsbuild import build_ics

ROOT = os.path.dirname(os.path.dirname(__file__))
STATE = os.path.join(ROOT, "state", "seen.json")
ICS_OUT = os.path.join(ROOT, "docs", "northwoods.ics")
REPORT = os.path.join(ROOT, "state", "last_run_report.json")

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
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return urljoin(source_url, url)

def main():
    cfg = load_yaml()
    tzname = cfg.get("timezone", "America/Chicago")
    default_minutes = int(cfg.get("default_duration_minutes", 60))
    seen = load_seen()
    tz = pytz.timezone(tzname)
    now = tz.localize(datetime.now())

    collected = []
    report = {"when": now.isoformat(), "sources": []}

    for s in cfg["sources"]:
        src_report = {"name": s["name"], "url": s["url"], "fetched": 0, "parsed": 0,
                      "added": 0, "skipped_past": 0, "skipped_nodate": 0, "skipped_dupe": 0,
                      "samples": []}
        try:
            html = get(s["url"])
            if s["type"] == "modern_tribe":
                rows = parse_mt(html)
            elif s["type"] == "growthzone":
                rows = parse_gz(html)
            else:
                rows = []
            src_report["fetched"] = len(rows)

            for r in rows:
                title = clean_text(r.get("title"))
                url = absolutize(r.get("url",""), s["url"])
                location = clean_text(r.get("venue_text") or "")
                # prefer ISO datetime if parser found one
                iso_from_attr = r.get("iso_datetime")
                date_text = clean_text(r.get("date_text") or "")

                start, end, all_day = parse_datetime_range(date_text, tzname, default_minutes, iso_hint=iso_from_attr)
                if not start or not end:
                    src_report["skipped_nodate"] += 1
                    if len(src_report["samples"]) < 5:
                        src_report["samples"].append({"reason":"nodate","title":title,"date_text":date_text,"iso_hint":iso_from_attr})
                    continue

                # Future or today only
                if start.replace(hour=0, minute=0, second=0, microsecond=0) < now.replace(hour=0, minute=0, second=0, microsecond=0):
                    src_report["skipped_past"] += 1
                    if len(src_report["samples"]) < 5:
                        src_report["samples"].append({"reason":"past","title":title,"start":start.isoformat(),"date_text":date_text})
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
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    build_ics(collected, ICS_OUT)

    # Persist state + report
    os.makedirs(os.path.join(ROOT, "state"), exist_ok=True)
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
                "skipped_dupe": s["skipped_dupe"]
            }
            for s in report["sources"]
        ]
    }
    print("SUMMARY:", json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
