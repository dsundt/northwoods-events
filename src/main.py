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
    if url.startswith("http"):
        return url
    return urljoin(source_url, url)

def main():
    cfg = load_yaml()
    tzname = cfg.get("timezone", "America/Chicago")
    default_minutes = int(cfg.get("default_duration_minutes", 60))
    seen = load_seen()
    now = pytz.timezone(tzname).localize(datetime.now())

    collected = []

    for s in cfg["sources"]:
        html = get(s["url"])
        if s["type"] == "modern_tribe":
            rows = parse_mt(html)
        elif s["type"] == "growthzone":
            rows = parse_gz(html)
        else:
            continue

        for r in rows:
            title = clean_text(r["title"])
            url = absolutize(r["url"], s["url"])
            location = clean_text(r.get("venue_text") or "")
            date_text = clean_text(r.get("date_text") or "")

            start, end, all_day = parse_datetime_range(date_text, tzname, default_minutes)
            if not start or not end:
                continue  # skip if cannot parse

            # Future or today only
            if start.replace(hour=0, minute=0, second=0, microsecond=0) < now.replace(hour=0, minute=0, second=0, microsecond=0):
                continue

            sid = stable_id(title, start.isoformat(), location, url)
            if sid in seen:
                continue  # already included

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

    # Build ICS
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    build_ics(collected, ICS_OUT)

    # Persist dedupe state
    os.makedirs(os.path.join(ROOT, "state"), exist_ok=True)
    save_seen(seen)

if __name__ == "__main__":
    main()
