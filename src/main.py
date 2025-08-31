import sys, os, json, yaml, datetime as dt
from typing import List, Dict

# local imports
from .scrapers.growthzone import scrape as scrape_growthzone
from .scrapers.modern_tribe import scrape as scrape_modern_tribe
from .scrapers.icsfeed import scrape as scrape_ics

STATE_DIR = "state"
EVENTS_PATH = os.path.join(STATE_DIR, "events.json")
REPORT_PATH = os.path.join(STATE_DIR, "last_run_report.json")
ICS_PATH = "northwoods.ics"

def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

def ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)

def normalize_kind(k: str) -> str:
    k = (k or "").strip().lower()
    if "growth" in k:
        return "growthzone"
    if "tribe" in k or "modern" in k:
        return "modern_tribe"
    if "ics" in k:
        return "ics"
    return k

def run(sources: List[Dict]) -> Dict:
    all_events: List[Dict] = []
    per = []

    print(f"Sources: {len(sources)}")
    for s in sources:
        name = s.get("name") or s.get("id") or "unknown"
        url = s.get("url")
        tzname = s.get("tzname") or "America/Chicago"
        kind = normalize_kind(s.get("kind"))

        parsed = added = 0
        try:
            if kind == "growthzone":
                items = scrape_growthzone(url, name=name, tzname=tzname, limit=150)
            elif kind == "modern_tribe":
                items = scrape_modern_tribe(url, name=name, tzname=tzname, limit=150)
            elif kind == "ics":
                items = scrape_ics(url, name=name, tzname=tzname, limit=500)
            else:
                items = []
                print(f"- {name} (unknown kind '{kind}') parsed: 0 added: 0")
                per.append({"name": name, "kind": kind, "url": url, "parsed": 0, "added": 0})
                continue

            parsed = len(items)
            # de-dup by (title,start,url)
            seen = set()
            keep = []
            for e in items:
                key = (e.get("title","").strip(), e.get("start",""), e.get("url","").strip())
                if key in seen: 
                    continue
                seen.add(key)
                keep.append(e)

            added = len(keep)
            all_events.extend(keep)
            print(f"- {name} ({s.get('kind')}) parsed: {parsed} added: {added}")
        except Exception as ex:
            print(f"- {name} ERROR: {ex}")
        finally:
            per.append({"name": name, "kind": kind, "url": url, "parsed": parsed, "added": added})

    # sort by start date
    def sort_key(e):
        return (e.get("start") or "9999-12-31T00:00:00Z", e.get("title",""))
    all_events.sort(key=sort_key)

    return {
        "when": now_utc_iso(),
        "total_events": len(all_events),
        "per_source": per,
        "events": all_events,
    }

def write_json(path: str, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def maybe_emit_ics(events: List[Dict]):
    try:
        from ics import Calendar, Event
        cal = Calendar()
        for e in events:
            ev = Event()
            ev.name = e.get("title")
            ev.begin = e.get("start")  # ISO8601 string
            if e.get("end"): ev.end = e["end"]
            ev.location = e.get("location")
            ev.url = e.get("url")
            ev.description = (e.get("description") or "")[:1000]
            cal.events.add(ev)
        with open(ICS_PATH, "w", encoding="utf-8") as w:
            w.writelines(cal.serialize_iter())
    except Exception as ex:
        print(f"[warn] could not build ICS: {ex}")

def main():
    ensure_dirs()
    raw = yaml.safe_load(sys.stdin.read()) if not sys.stdin.closed else {}
    sources = (raw or {}).get("sources", [])
    if not sources:
        print("ERROR: no sources on stdin")
        write_json(EVENTS_PATH, [])
        write_json(REPORT_PATH, {"when": now_utc_iso(), "total_events": 0, "per_source": []})
        return

    report = run(sources)
    events = report.pop("events", [])
    write_json(EVENTS_PATH, events)
    write_json(REPORT_PATH, {**report})  # without events (keeps file small)

    # Optional: emit combined ICS
    if events:
        maybe_emit_ics(events)

if __name__ == "__main__":
    main()
