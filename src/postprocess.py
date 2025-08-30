# src/postprocess.py
import os
import json
import re
import sys
from datetime import datetime
from urllib.parse import urlparse
from dateutil import parser as duparser
import pytz

CT = pytz.timezone("America/Chicago")

# --- Tuning via env vars (safe defaults) ---
JSONLD_ENABLE = os.environ.get("JSONLD_ENABLE", "1") == "1"
JSONLD_MAX = int(os.environ.get("JSONLD_MAX", "60"))               # hard cap on total fetches
JSONLD_PER_DOMAIN = int(os.environ.get("JSONLD_PER_DOMAIN", "12")) # per-domain cap
JSONLD_TIMEOUT = float(os.environ.get("JSONLD_TIMEOUT", "4.0"))    # seconds

# Only enrich if the source is likely to have JSON-LD and we need it
JSONLD_ALLOW_SOURCES = {
    # Modern Tribe (common across many of your sites)
    "Vilas County (Modern Tribe)",
    "Boulder Junction (Modern Tribe)",
    "Eagle River Chamber (Modern Tribe)",
    "St. Germain Chamber (Modern Tribe)",
    "Sayner–Star Lake–Cloverland Chamber (Modern Tribe)",
    "Sayner-Star Lake-Cloverland Chamber (Modern Tribe)",
    "Oneida County – Festivals & Events (Modern Tribe)",
    "Oneida County Festivals and Events (Modern Tribe)",
    # Simpleview that you’re keeping (Minocqua)
    "Minocqua Area Chamber (Simpleview)",
    # AI1EC / municipal sometimes has JSON-LD
    "Town of Arbor Vitae (Municipal Calendar)",
}

# Drop these sources outright (per your earlier requests)
DROP_SOURCES = {
    "Oneida County Festivals and Events (Simpleview)",
    "Sayner–Star Lake–Cloverland Chamber (Modern Tribe)",
    "Sayner-Star Lake-Cloverland Chamber (Modern Tribe)",
    "Presque Isle (Modern Tribe)",
}

BAD_URL_SNIPPETS = ("/series/", "/category/", "/tag/", "/all/", "/tools")
BAD_TITLE_RX = re.compile(r"^(events\s+for|calendar\s+of\s+events|find\s+events)\b", re.I)

def to_local_iso(dt_str: str) -> str | None:
    if not dt_str:
        return None
    try:
        dt = duparser.isoparse(dt_str)
    except Exception:
        try:
            dt = duparser.parse(dt_str)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = CT.localize(dt)
    else:
        dt = dt.astimezone(CT)
    return dt.isoformat()

def derive_title_from_url(url: str) -> str | None:
    if not url:
        return None
    slug = url.strip("/").split("/")[-1]
    if not slug:
        return None
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\b(all|series|category|tag)\b", "", slug, flags=re.I).strip()
    if slug:
        return slug.title()
    return None

class JsonLdFetcher:
    def __init__(self, max_total: int, per_domain: int, timeout: float, enabled: bool):
        self.max_total = max_total
        self.per_domain = per_domain
        self.timeout = timeout
        self.enabled = enabled
        self.total = 0
        self.per_domain_count = {}
        self.cache_path = os.path.join(os.getcwd(), "state", "jsonld_cache.json")
        self.cache = {}
        if os.path.exists(self.cache_path):
            try:
                self.cache = json.load(open(self.cache_path, "r", encoding="utf-8"))
            except Exception:
                self.cache = {}

    def _can_fetch(self, url: str) -> bool:
        if not self.enabled or not url or any(s in url for s in BAD_URL_SNIPPETS):
            return False
        if url in self.cache:
            return True  # cached ok
        if self.total >= self.max_total:
            return False
        host = urlparse(url).netloc.lower()
        if not host:
            return False
        if self.per_domain_count.get(host, 0) >= self.per_domain:
            return False
        return True

    def _record_fetch(self, url: str):
        self.total += 1
        host = urlparse(url).netloc.lower()
        self.per_domain_count[host] = self.per_domain_count.get(host, 0) + 1

    def fetch(self, url: str) -> dict | None:
        # Return cached result if present
        if url in self.cache:
            return self.cache[url]
        if not self._can_fetch(url):
            return None
        try:
            import requests
            from bs4 import BeautifulSoup
        except Exception:
            return None
        self._record_fetch(url)
        try:
            r = requests.get(url, timeout=self.timeout, headers={"User-Agent": "northwoods-events-normalizer"})
            if r.status_code != 200 or not r.text:
                return None
            soup = BeautifulSoup(r.text, "lxml")
            for tag in soup.find_all("script", {"type": "application/ld+json"}):
                raw = tag.string or tag.text
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                nodes = data if isinstance(data, list) else [data]
                for node in nodes:
                    types = node.get("@type")
                    if isinstance(types, list):
                        is_event = any(isinstance(t, str) and t.lower() == "event" for t in types)
                    else:
                        is_event = isinstance(types, str) and types.lower() == "event"
                    if not is_event:
                        continue
                    out = {}
                    if isinstance(node.get("name"), str):
                        out["name"] = node["name"]
                    if isinstance(node.get("startDate"), str):
                        out["startDate"] = node["startDate"]
                    if isinstance(node.get("endDate"), str):
                        out["endDate"] = node["endDate"]
                    loc = node.get("location")
                    if isinstance(loc, dict):
                        if isinstance(loc.get("name"), str) and loc["name"].strip():
                            out["locationName"] = loc["name"].strip()
                        addr = loc.get("address")
                        if isinstance(addr, dict):
                            parts = [addr.get(k, "") for k in ("streetAddress", "addressLocality", "addressRegion")]
                            parts = [p for p in parts if p]
                            if parts:
                                out["locationAddr"] = ", ".join(parts)
                    if out:
                        self.cache[url] = out
                        # Persist cache as we go (best effort; ignore errors)
                        try:
                            os.makedirs(os.path.join(os.getcwd(), "state"), exist_ok=True)
                            json.dump(self.cache, open(self.cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                        except Exception:
                            pass
                        return out
        except Exception:
            return None
        return None

def enrich_from_jsonld(ev: dict, fetcher: JsonLdFetcher) -> dict:
    url = ev.get("url") or ""
    if not url:
        return ev
    source = (ev.get("source") or "").strip()
    # only enrich if allowed AND we actually need data
    need_start = not ev.get("start_iso")
    need_title = not (ev.get("title") or "").strip()
    need_location = not (ev.get("location") or "").strip()
    if source not in JSONLD_ALLOW_SOURCES or not (need_start or need_title or need_location):
        return ev

    info = fetcher.fetch(url)
    if not info:
        return ev

    if need_title and isinstance(info.get("name"), str) and info["name"].strip():
        ev["title"] = info["name"].strip()

    if need_start and isinstance(info.get("startDate"), str):
        iso = to_local_iso(info["startDate"])
        if iso:
            ev["start_iso"] = iso

    if not ev.get("end_iso") and isinstance(info.get("endDate"), str):
        iso = to_local_iso(info["endDate"])
        if iso:
            ev["end_iso"] = iso

    if need_location:
        loc = info.get("locationName") or info.get("locationAddr")
        if loc:
            ev["location"] = loc
    return ev

def normalize_one(ev: dict, fetcher: JsonLdFetcher) -> tuple[bool, dict | str]:
    source = (ev.get("source") or "").strip()

    # 1) drop unwanted sources
    if source in DROP_SOURCES:
        return False, f"dropped_by_source:{source}"

    # 2) convert legacy 'start'/'end' fields to iso
    if not ev.get("start_iso") and ev.get("start"):
        iso = to_local_iso(ev.get("start"))
        if iso: ev["start_iso"] = iso
    if not ev.get("end_iso") and ev.get("end"):
        iso = to_local_iso(ev.get("end"))
        if iso: ev["end_iso"] = iso

    # 3) filter non-event pages
    url = (ev.get("url") or "")
    if any(s in url for s in BAD_URL_SNIPPETS):
        return False, "listing_or_series_url"

    # 4) title fallback
    title = (ev.get("title") or "").strip()
    if not title or title.lower() in {"recurring", "untitled", ""}:
        derived = derive_title_from_url(url)
        if derived:
            ev["title"] = derived

    # 5) JSON-LD enrichment (strictly capped)
    ev = enrich_from_jsonld(ev, fetcher)

    # 6) drop garbage titles
    if BAD_TITLE_RX.search(ev.get("title") or ""):
        return False, "garbage_title"

    # 7) must have start date
    if not ev.get("start_iso"):
        return False, "no_start_after_enrichment"

    # 8) finalize flags
    ev["all_day"] = bool(ev.get("all_day", False))
    return True, ev

def main():
    root = os.getcwd()
    candidates = [
        os.path.join(root, "state", "events.json"),
        os.path.join(root, "events.json"),
    ]
    src_path = next((p for p in candidates if os.path.isfile(p)), None)
    if not src_path:
        print("No events store found. Skipping postprocess.")
        return 0

    with open(src_path, "r", encoding="utf-8") as f:
        store = json.load(f)

    fetcher = JsonLdFetcher(JSONLD_MAX, JSONLD_PER_DOMAIN, JSONLD_TIMEOUT, JSONLD_ENABLE)

    kept = {}
    dropped = {}
    for key, ev in store.items():
        keep, result = normalize_one(dict(ev), fetcher)
        if not keep:
            dropped[result] = dropped.get(result, 0) + 1
            continue
        nk = f"{result.get('source','')}|{result.get('title','')}|{result.get('start_iso','')}"
        kept[nk] = result

    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    os.makedirs(os.path.join(root, "public", "state"), exist_ok=True)
    os.makedirs(os.path.join(root, "public", "ics"), exist_ok=True)

    normalized_path = os.path.join(root, "state", "events.normalized.json")
    with open(normalized_path, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    canonical = os.path.join(root, "state", "events.json")
    with open(canonical, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    validation = {
        "input_events": len(store),
        "output_events": len(kept),
        "dropped_by_reason": dropped,
        "jsonld": {
            "enabled": JSONLD_ENABLE,
            "max_total": JSONLD_MAX,
            "per_domain": JSONLD_PER_DOMAIN,
            "timeout_sec": JSONLD_TIMEOUT,
            "fetched_total": fetcher.total,
            "per_domain_counts": fetcher.per_domain_count,
        },
        "note": "Dates normalized to America/Chicago; sources filtered; capped JSON-LD enrichment applied only when needed.",
    }
    with open(os.path.join(root, "state", "validation.json"), "w", encoding="utf-8") as f:
        json.dump(validation, f, ensure_ascii=False, indent=2)

    # Build ICS
    try:
        from ics import Calendar, Event
        cal = Calendar()
        for ev in kept.values():
            e = Event()
            e.name = (ev.get("title") or "Untitled").strip()
            e.begin = ev.get("start_iso")
            if ev.get("end_iso"):
                e.end = ev["end_iso"]
            e.make_all_day = bool(ev.get("all_day", False))
            if ev.get("location"):
                e.location = ev["location"]
            if ev.get("url"):
                e.url = ev["url"]
            if ev.get("description"):
                e.description = ev["description"]
            cal.events.add(e)
        with open(os.path.join(root, "northwoods.ics"), "w", encoding="utf-8") as f:
            f.write(str(cal))
    except Exception as e:
        print("ICS generation skipped:", repr(e))

    # Copy to public for Pages
    try:
        import shutil
        shutil.copy(canonical, os.path.join(root, "public", "state", "events.json"))
        if os.path.exists(os.path.join(root, "state", "last_run_report.json")):
            shutil.copy(os.path.join(root, "state", "last_run_report.json"), os.path.join(root, "public", "state", "last_run_report.json"))
        shutil.copy(os.path.join(root, "state", "validation.json"), os.path.join(root, "public", "state", "validation.json"))
        if os.path.exists(os.path.join(root, "northwoods.ics")):
            shutil.copy(os.path.join(root, "northwoods.ics"), os.path.join(root, "public", "ics", "northwoods.ics"))
    except Exception:
        pass

    print(f"Postprocess complete. Input: {len(store)}  Output: {len(kept)}  Dropped: {sum(dropped.values())}  JSONLD fetched: {fetcher.total}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
