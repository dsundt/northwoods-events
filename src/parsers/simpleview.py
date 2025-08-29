from __future__ import annotations
import json
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _as_items_from_jsonld(soup, base_url: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "{}")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if (obj or {}).get("@type") in ("Event",):
                name = obj.get("name", "")
                start = obj.get("startDate", "") or obj.get("startTime", "")
                url = obj.get("url", base_url)
                loc = ""
                loc_obj = obj.get("location")
                if isinstance(loc_obj, dict):
                    loc = loc_obj.get("name") or _text(loc_obj.get("address"))
                out.append({"title": name, "start": start, "url": url, "location": loc})
    return out

def _as_items_from_cards(soup, base_url: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # Typical Simpleview listing cards
    cards = soup.select("[class*=event] a, .teaser a, .listing a")
    if not cards:
        cards = soup.find_all("a", href=True)
    for a in cards:
        href = a.get("href", "")
        if not href:
            continue
        # Prefer event detail pages when obvious
        if "/event/" not in href and "/events/" not in href:
            continue
        title = _text(a).strip()
        if not title:
            # look up to parent heading
            h = a.find_parent().find(["h3","h2"]) if a.find_parent() else None
            title = _text(h)
        if not title:
            continue
        out.append({"title": title, "start": "", "url": urljoin(base_url, href), "location": ""})
    return out

def _as_items_from_hub_links(soup, base_url: str) -> List[Dict[str, Any]]:
    """When a page is just a hub with 'See more events here' links, return those."""
    out: List[Dict[str, Any]] = []
    for a in soup.find_all("a", href=True):
        txt = _text(a).lower()
        if "events" in txt and ("here" in txt or "calendar" in txt):
            out.append({"title": _text(a), "start": "", "url": urljoin(base_url, a["href"]), "location": ""})
    return out

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items = []

    items.extend(_as_items_from_jsonld(soup, base_url))
    if not items:
        items.extend(_as_items_from_cards(soup, base_url))
    if not items:
        items.extend(_as_items_from_hub_links(soup, base_url))

    # Deduplicate by URL
    seen = set()
    deduped = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        deduped.append(it)

    return deduped[:200]
