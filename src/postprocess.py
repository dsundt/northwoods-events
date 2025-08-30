# src/postprocess.py
import json, os, re, sys, logging, time
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

ROOT = os.path.abspath(os.getcwd())
STATE_PATH = os.environ.get("EVENTS_JSON", os.path.join(ROOT, "state", "events.json"))

session = requests.Session()
session.headers.update({
    "User-Agent":"northwoods-events-bot/1.0 (+github actions)",
    "Accept":"text/html,application/xhtml+xml,application/xml"
})

def is_series_url(u):
    return "/series/" in u

def is_day_view_url(u):
    return re.search(r"/events/\d{4}-\d{2}-\d{2}/?$", u) is not None or u.rstrip("/").endswith("/events")

def is_modern_tribe_detail(u):
    return re.search(r"/events/[^/]+/(\d{4}-\d{2}-\d{2}/?)?$", u) is not None

def is_simpleview_detail(u):
    return re.search(r"/event(s)?/[^/]+/?$", u) is not None

def is_bad_misc_page(u):
    bad = ["privacy-policy","places-to-stay","hiking","paddling","swimming","find-businesses"]
    return any(f"/{b}" in u for b in bad)

def fetch_jsonld(url, timeout=20):
    try:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all("script", attrs={"type":"application/ld+json"}):
            try:
                txt = tag.string or tag.text
                if not txt:
                    continue
                data = json.loads(txt)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                t = item.get("@type") or item.get("@context")
                t = t if isinstance(t, str) else str(t)
                if "Event" in t:
                    return item
                if "EventSeries" in t:
                    return item
        title = soup.find("meta", property="og:title")
        if title:
            return {"@type":"Thing", "name": title.get("content","").strip()}
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return {"@type":"Thing", "name": h1.get_text(strip=True)}
    except Exception as e:
        logging.warning("json-ld fetch failed for %s: %s", url, e)
    return None

def enrich_from_jsonld(ev, item):
    changed = False
    if not ev.get("title"):
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            ev["title"] = name.strip()
            changed = True
    start = item.get("startDate")
    end = item.get("endDate")
    if start and not ev.get("start_iso"):
        ev["start_iso"] = start
        changed = True
    if end and not ev.get("end_iso"):
        ev["end_iso"] = end
        changed = True
    if not ev.get("location"):
        loc = item.get("location")
        if isinstance(loc, dict):
            nm = loc.get("name","")
            addr = loc.get("address",{})
            if isinstance(addr, dict):
                parts = [nm, addr.get("streetAddress",""), addr.get("addressLocality",""), addr.get("addressRegion","")]
                loc_str = ", ".join([p for p in parts if p])
            else:
                loc_str = nm
            if loc_str:
                ev["location"] = loc_str
                changed = True
    return changed

def keep_event(ev):
    url = ev.get("url","") or ""
    src = ev.get("source","")
    url = url if url.startswith("http") else url

    if "Modern Tribe" in src:
        if is_series_url(url): return False, "drop: series url"
        if is_day_view_url(url): return False, "drop: day view url"
        if not is_modern_tribe_detail(url):
            if not ev.get("title") or not ev.get("start_iso"):
                return False, "drop: not a detail event page"
    if "Simpleview" in src:
        if not is_simpleview_detail(url):
            if not ev.get("title") or not ev.get("start_iso"):
                return False, "drop: simpleview non-detail"
    if "Municipal Calendar" in src or "ai1ec" in src.lower():
        if url.startswith("tel:") or "google.com/maps" in url:
            return False, "drop: contact/map link"
        if not ev.get("start_iso"):
            return False, "drop: missing date"
    if "GrowthZone" in src:
        if not ev.get("start_iso"):
            return False, "drop: missing date"
    if is_bad_misc_page(url): return False, "drop: misc page"
    return True, "keep"

def main():
    if not os.path.exists(STATE_PATH):
        logging.error("events.json not found at %s", STATE_PATH)
        sys.exit(1)
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        store = json.load(f)

    out = {}
    touched = 0
    dropped = 0
    enriched = 0

    for key, ev in store.items():
        ok, reason = keep_event(ev)
        if not ok:
            dropped += 1
            continue

        if (not ev.get("title")) or (not ev.get("start_iso")) or (not ev.get("location")):
            url = ev.get("url","")
            if url.startswith("http"):
                item = fetch_jsonld(url)
                if item:
                    if enrich_from_jsonld(ev, item):
                        enriched += 1
                        ev.setdefault("trace", {})["enriched_from"] = "json-ld"
        if not ev.get("title") or not ev.get("start_iso"):
            dropped += 1
            continue

        out[key] = ev
        touched += 1

    logging.info("Loaded: %d  -> kept: %d, dropped: %d, enriched: %d", len(store), touched, dropped, enriched)

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)

    public_state = os.path.join(ROOT, "public", "state")
    try:
        os.makedirs(public_state, exist_ok=True)
        with open(os.path.join(public_state, "events.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as e:
        logging.warning("Could not write public/state/events.json: %s", e)

if __name__ == "__main__":
    main()
