# src/postprocess.py
import os
import json
import re
import sys
from datetime import datetime
from dateutil import parser as duparser
import pytz

CT = pytz.timezone("America/Chicago")

# ---- configuration ----

# Completely drop these sources from the feed (you asked to keep ICS-only for some)
DROP_SOURCES = {
    # Oneida Simpleview – remove
    "Oneida County Festivals and Events (Simpleview)",
    # Sayner Modern Tribe – remove (keep ICS, see below)
    "Sayner–Star Lake–Cloverland Chamber (Modern Tribe)",
    "Sayner-Star Lake-Cloverland Chamber (Modern Tribe)",
    # Presque Isle Modern Tribe – remove (keep ICS)
    "Presque Isle (Modern Tribe)",
}

# URLs to treat as *not* individual events (aggregators, series, category pages, tools, etc.)
BAD_URL_SNIPPETS = (
    "/series/",
    "/category/",
    "/tag/",
    "/all/",
    "/tools",
)

# Titles that are clearly not an event title
BAD_TITLE_RX = re.compile(r"^(events\s+for|calendar\s+of\s+events|find\s+events)\b", re.I)

# ---- helpers ----

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

def enrich_from_jsonld(ev: dict) -> dict:
    """
    Fetch JSON-LD from the event URL and copy in name, startDate, endDate, and location if present.
    This is a best-effort enrichment only; failures are silent.
    """
    url = ev.get("url") or ""
    if not url or any(s in url for s in BAD_URL_SNIPPETS):
        return ev
    try:
        import requests
        from bs4 import BeautifulSoup
    except Exception:
        # If dependencies unavailable for any reason, skip enrichment safely.
        return ev

    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "northwoods-events-normalizer"})
        if r.status_code != 200 or not r.text:
            return ev
        soup = BeautifulSoup(r.text, "lxml")
        # find all JSON-LD blocks
        for tag in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                raw = tag.string or tag.text
                if not raw:
                    continue
                data = json.loads(raw)
            except Exception:
                continue

            nodes = data if isinstance(data, list) else [data]
            # find an Event node
            for node in nodes:
                types = node.get("@type")
                if isinstance(types, list):
                    is_event = any(t.lower() == "event" for t in types if isinstance(t, str))
                else:
                    is_event = isinstance(types, str) and types.lower() == "event"
                if not is_event:
                    continue

                # Copy what we can
                if not (ev.get("title") or "").strip():
                    name = node.get("name")
                    if isinstance(name, str) and name.strip():
                        ev["title"] = name.strip()

                if not ev.get("start_iso"):
                    sd = node.get("startDate")
                    if isinstance(sd, str):
                        iso = to_local_iso(sd)
                        if iso:
                            ev["start_iso"] = iso

                if not ev.get("end_iso"):
                    ed = node.get("endDate")
                    if isinstance(ed, str):
                        iso = to_local_iso(ed)
                        if iso:
                            ev["end_iso"] = iso

                if not ev.get("location"):
                    loc = node.get("location")
                    if isinstance(loc, dict):
                        # Accept either "name" or a compact address
                        name = loc.get("name")
                        if name:
                            ev["location"] = str(name)
                        else:
                            addr = loc.get("address")
                            if isinstance(addr, dict):
                                parts = [addr.get(k, "") for k in ("streetAddress", "addressLocality", "addressRegion")]
                                parts = [p for p in parts if p]
                                if parts:
                                    ev["location"] = ", ".join(parts)
                # If we enriched *anything* from the first Event node, we're done.
                return ev

    except Exception:
        return ev

    return ev

def normalize_one(ev: dict) -> tuple[bool, dict]:
    """
    Returns (keep, normalized_event_or_reason)
    If keep is False, second item is a string drop reason.
    If keep is True, second item is the normalized event dict.
    """
    source = (ev.get("source") or "").strip()

    # 1) filter sources we must remove completely
    if source in DROP_SOURCES:
        return False, f"dropped_by_source:{source}"

    # 2) convert legacy 'start'/'end' fields used by some scrapers
    if not ev.get("start_iso"):
        if ev.get("start"):
            iso = to_local_iso(ev.get("start"))
            if iso:
                ev["start_iso"] = iso
    if not ev.get("end_iso"):
        if ev.get("end"):
            iso = to_local_iso(ev.get("end"))
            if iso:
                ev["end_iso"] = iso

    # 3) drop clearly non-event URLs (series/category/tools/etc.)
    url = (ev.get("url") or "")
    if any(s in url for s in BAD_URL_SNIPPETS):
        return False, "listing_or_series_url"

    # 4) fill missing title from URL slug (many “Untitled” / “Recurring”)
    title = (ev.get("title") or "").strip()
    if not title or title.lower() in {"recurring", "untitled", ""}:
        derived = derive_title_from_url(url)
        if derived:
            ev["title"] = derived

    # 5) JSON-LD enrichment (for pages that expose proper machine data)
    if not ev.get("start_iso") or not ev.get("title") or not ev.get("location"):
        ev = enrich_from_jsonld(ev)

    # 6) drop garbage titles
    if BAD_TITLE_RX.search(ev.get("title") or ""):
        return False, "garbage_title"

    # 7) must have a start date at this point
    if not ev.get("start_iso"):
        return False, "no_start_after_enrichment"

    # 8) normalize booleans and keep expected keys
    ev["all_day"] = bool(ev.get("all_day", False))

    return True, ev

def main():
    root = os.getcwd()
    # Prefer state/events.json (created by your scrape) but fall back to events.json
    candidates = [
        os.path.join(root, "state", "events.json"),
        os.path.join(root, "events.json"),
    ]
    src_path = None
    for p in candidates:
        if os.path.isfile(p):
            src_path = p
            break

    if not src_path:
        print("No events store found. Skipping postprocess.")
        return 0

    with open(src_path, "r", encoding="utf-8") as f:
        store = json.load(f)

    kept = {}
    dropped = {}
    fixed = 0

    for key, ev in store.items():
        keep, result = normalize_one(dict(ev))
        if not keep:
            dropped[result] = dropped.get(result, 0) + 1
            continue
        # re-key with a stable key (source + title + start)
        nk = f"{result.get('source','')}|{result.get('title','')}|{result.get('start_iso','')}"
        kept[nk] = result
        fixed += 1

    # Ensure output dirs exist
    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    os.makedirs(os.path.join(root, "public", "state"), exist_ok=True)
    os.makedirs(os.path.join(root, "public", "ics"), exist_ok=True)

    # 1) Write normalized store side-by-side (and replace the canonical events.json so site uses it)
    normalized_path = os.path.join(root, "state", "events.normalized.json")
    with open(normalized_path, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    canonical = os.path.join(root, "state", "events.json")
    with open(canonical, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    # 2) Validation summary (for debugging on the page)
    validation = {
        "input_events": len(store),
        "output_events": len(kept),
        "dropped_by_reason": dropped,
        "note": "Dates normalized to America/Chicago; sources filtered per requirements; JSON-LD enrichment applied when available.",
    }
    with open(os.path.join(root, "state", "validation.json"), "w", encoding="utf-8") as f:
        json.dump(validation, f, ensure_ascii=False, indent=2)

    # 3) Build ICS from normalized events (best effort)
    try:
        from ics import Calendar, Event
        cal = Calendar()
        for ev in kept.values():
            name = (ev.get("title") or "Untitled").strip()
            start_iso = ev.get("start_iso")
            if not start_iso:
                continue
            e = Event()
            e.name = name
            e.begin = start_iso
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
        ics_text = str(cal)
        with open(os.path.join(root, "northwoods.ics"), "w", encoding="utf-8") as f:
            f.write(ics_text)
    except Exception as e:
        print("ICS generation skipped:", repr(e))

    # Copy public artifacts (the workflow also copies, but doing it here makes local runs easier)
    try:
        import shutil
        shutil.copy(canonical, os.path.join(root, "public", "state", "events.json"))
        shutil.copy(os.path.join(root, "state", "validation.json"), os.path.join(root, "public", "state", "validation.json"))
        if os.path.exists(os.path.join(root, "state", "last_run_report.json")):
            shutil.copy(os.path.join(root, "state", "last_run_report.json"), os.path.join(root, "public", "state", "last_run_report.json"))
        if os.path.exists(os.path.join(root, "northwoods.ics")):
            shutil.copy(os.path.join(root, "northwoods.ics"), os.path.join(root, "public", "ics", "northwoods.ics"))
    except Exception:
        pass

    print(f"Postprocess complete. Input: {len(store)}  Output: {len(kept)}  Dropped: {sum(dropped.values())}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
