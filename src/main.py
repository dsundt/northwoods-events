import sys, os, json, io, datetime as dt, pytz, yaml, traceback
from typing import List, Dict, Any, Tuple

from resolve_sources import resolve_sources
from fetch import fetch_html, fetch_text
from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone
from parsers.simpleview import parse_simpleview
from parsers.ics_feed import parse_ics

STATE_DIR = "state"
EVENTS_PATH = os.path.join(STATE_DIR, "events.json")
LAST_RUN_PATH = os.path.join(STATE_DIR, "last_run_report.json")
DEBUG = bool(os.environ.get("DEBUG_SCRAPER"))

def ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(os.path.join(STATE_DIR, "debug"), exist_ok=True)

def write_json(path: str, data: Any):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as w:
        json.dump(data, w, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def summarize_print(name: str, kind: str, parsed: int, added: int, error: str = None):
    if error:
        print(f"- {name} ({kind}) ERROR: {error}")
    else:
        print(f"- {name} ({kind}) parsed: {parsed} added: {added}")

def load_sources_from_stdin() -> List[Dict[str, Any]]:
    raw = sys.stdin.read()
    cfg = yaml.safe_load(raw) or {}
    return resolve_sources(cfg.get("sources", []))

def parse_one(source: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    """
    Returns (events, report, error)
    """
    name = source["name"]
    kind = source["kind"]
    url  = source["url"]
    tzname = source.get("tzname")

    try:
        if kind == "modern_tribe":
            html, final_url = fetch_html(url, wait_for=":is(.tribe-events,.tec-events,.tribe-common)")
            events = parse_modern_tribe(html, base_url=final_url, tzname=tzname, source_name=name)
        elif kind == "growthzone":
            html, final_url = fetch_html(url, wait_for="body")
            events = parse_growthzone(html, base_url=final_url, tzname=tzname, source_name=name)
        elif kind == "simpleview":
            html, final_url = fetch_html(url, wait_for="body")
            events = parse_simpleview(html, base_url=final_url, tzname=tzname, source_name=name)
        elif kind == "ics":
            text, final_url = fetch_text(url)
            events = parse_ics(text, tzname=tzname, source_name=name)
        else:
            return [], {}, f"unknown kind '{kind}'"

        parsed = len(events)
        # Dedup by (title,start,url)
        seen = set()
        deduped = []
        for e in events:
            key = (e.get("title","").strip(), e.get("start"), e.get("url","").strip())
            if key in seen: 
                continue
            seen.add(key)
            deduped.append(e)

        report = {"name": name, "kind": kind, "url": url, "parsed": parsed, "added": len(deduped)}
        return deduped, report, None
    except Exception as ex:
        if DEBUG:
            traceback.print_exc()
        return [], {"name": name, "kind": kind, "url": url, "parsed": 0, "added": 0}, str(ex)

def main():
    ensure_dirs()
    sources = load_sources_from_stdin()
    print(f"Sources: {len(sources)}")

    all_events: List[Dict[str, Any]] = []
    per_source: List[Dict[str, Any]] = []

    for src in sources:
        evs, rep, err = parse_one(src)
        per_source.append(rep)
        summarize_print(rep.get("name", "?"), rep.get("kind","?"), rep.get("parsed",0), rep.get("added",0), err)
        # keep only added events
        all_events.extend(evs)

    # Sort by start datetime string (ISO sorts fine)
    def _dt_key(v):
        return v.get("start") or ""
    all_events.sort(key=_dt_key)

    # Write outputs
    write_json(EVENTS_PATH, all_events)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    last = {"when": now, "total_events": len(all_events), "per_source": per_source}
    write_json(LAST_RUN_PATH, last)

if __name__ == "__main__":
    main()
