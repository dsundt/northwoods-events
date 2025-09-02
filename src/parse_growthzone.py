# src/parse_growthzone.py
from __future__ import annotations
import requests, re, json
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from .utils.jsonld import extract_events_from_jsonld
from .utils import norm_event, clean_text, save_debug_html

UA = "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0; +https://example.invalid)"

def _fetch_html(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text

def parse_growthzone(name: str, url: str, tzname: Optional[str] = None) -> List[Dict[str, Any]]:
    html = _fetch_html(url)
    save_debug_html(html, filename=f"growthzone_{name.replace(' ','_')}")
    # 1) Prefer JSON-LD (GrowthZone usually includes it)
    events = extract_events_from_jsonld(html, source_name=name, default_tz=tzname)
    if events:
        return [norm_event(e) for e in events]

    # 2) Fallback: some GrowthZone pages embed a JSON variable with events
    #    Look for window.__INITIAL_STATE__ or similar.
    m = re.search(r"__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.DOTALL)
    out: List[Dict[str, Any]] = []
    if m:
        try:
            state = json.loads(m.group(1))
            # Heuristic path search for "events"
            def walk(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k.lower() == "events" and isinstance(v, list):
                            yield v
                        else:
                            yield from walk(v)
                elif isinstance(obj, list):
                    for it in obj:
                        yield from walk(it)
            for evlist in walk(state):
                for ev in evlist:
                    title = clean_text(str(ev.get("title") or ev.get("name") or ""))
                    start = ev.get("start") or ev.get("startDate")
                    end = ev.get("end") or ev.get("endDate")
                    href = ev.get("url") or url
                    venue = ev.get("venue") or ev.get("location") or ""
                    if title and start:
                        out.append(norm_event({
                            "title": title,
                            "start": start,
                            "end": end,
                            "url": href,
                            "location": clean_text(str(venue)),
                            "source": name,
                        }))
            if out:
                return out
        except Exception:
            pass

    # 3) Minimal HTML fallback to avoid returning nothing
    soup = BeautifulSoup(html, "lxml")
    for a in soup.select("a[href*='/events/details/']"):
        title = clean_text(a.get_text(" ", strip=True))
        href = a["href"]
        if title:
            out.append(norm_event({"title": title, "url": href, "start": None, "end": None, "location": "", "source": name}))
    return out
