from __future__ import annotations
from typing import List, Dict, Any, Optional
import logging
from urllib.parse import urljoin
import requests

from utils.fetchers import try_wp_tec_json, fetch_rendered, site_root

def _coalesce(*vals):
    for v in vals:
        if v:
            return v
    return None

def _norm_title(ev: dict) -> str:
    # TEC JSON typically returns 'title' and 'title_plain'; also some variants use 'name'
    return _coalesce(ev.get("title_plain"), ev.get("title"), ev.get("name")) or ""

def _norm_url(ev: dict) -> str:
    return _coalesce(ev.get("url"), ev.get("link"), "")

def _norm_start(ev: dict) -> str:
    # TEC JSON commonly uses 'start_date'; some variants use 'start' or 'date'
    return _coalesce(ev.get("start_date"), ev.get("start"), ev.get("date")) or ""

def _norm_venue(ev: dict) -> str:
    venue = ev.get("venue") or {}
    if isinstance(venue, dict):
        name = venue.get("venue") or venue.get("name") or ""
        addr = ", ".join(filter(None, [
            venue.get("address"), venue.get("city"), venue.get("state"), venue.get("country")
        ]))
        return (name + (" " + addr if addr else "")).strip()
    return ""

def _parse_from_tec_json(data: dict) -> List[Dict[str, Any]]:
    # TEC v1 returns {"events": [ ... ]} or sometimes nested under "data"
    events = data.get("events")
    if events is None and isinstance(data.get("data"), dict):
        events = data["data"].get("events")

    items: List[Dict[str, Any]] = []
    if not isinstance(events, list):
        return items

    for ev in events:
        title = _norm_title(ev).strip()
        url = _norm_url(ev).strip()
        start = _norm_start(ev).strip()
        if not (title and url and start):
            continue
        items.append({
            "title": title,
            "start": start,
            "url": url,
            "location": _norm_venue(ev),
        })
    return items

def _ajax_candidates(base_url: str) -> list[dict]:
    """
    Potential AJAX endpoints (best-effort). We try TEC first via try_wp_tec_json.
    You can add custom endpoints here if St. Germain uses Micronet/GrowthZone embeds.
    """
    root = site_root(base_url)
    # Example placeholder for a custom Micronet endpoint if known:
    return [
        {"method": "GET", "url": urljoin(root, "/wp-admin/admin-ajax.php"), "params": {"action": "tribe_events_list"}}
    ]

def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Strategy:
      1) Try WordPress TEC JSON (if the site uses The Events Calendar).
      2) Try any additional AJAX endpoints you configure.
      3) Fallback: render the calendar list page and scrape anchors (Playwright).
    """
    # (1) TEC JSON
    data = try_wp_tec_json(base_url)
    if data:
        items = _parse_from_tec_json(data)
        if items:
            return items

    # (2) Other AJAX candidates (best-effort GET)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0)"}
    for cand in _ajax_candidates(base_url):
        try:
            r = requests.request(cand["method"], cand["url"], params=cand.get("params"), headers=headers, timeout=20)
            if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
                # If it returns an HTML fragment of event cards, we can try scraping like Modern Tribe.
                from bs4 import BeautifulSoup
                from urllib.parse import urljoin as _u
                soup = BeautifulSoup(r.text, "html.parser")
                items: List[Dict[str, Any]] = []
                for a in soup.select("a[href]"):
                    href = a.get("href", "")
                    title = " ".join(a.stripped_strings)
                    if not title or not href:
                        continue
                    # extremely permissive, to at least return something. You can tighten to '.tribe-events-*' if needed.
                    items.append({
                        "title": title.strip(),
                        "start": "",  # unknown in generic fragment
                        "url": _u(base_url, href),
                        "location": "",
                    })
                if items:
                    return items
        except Exception as e:
            logging.info("AJAX candidate failed: %s", e)

    # (3) Render the list page (JS) and scrape anchor cards as a last resort
    rendered = fetch_rendered(base_url, wait_selector="a")
    if not rendered:
        logging.warning("St. Germain AJAX: fell back to static; no events.")
        return []

    # Use very generic scraping (titles + links). If you know the exact classes, tighten selectors here.
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin as _u
    soup = BeautifulSoup(rendered, "html.parser")
    items: List[Dict[str, Any]] = []
    seen = set()
    for a in soup.select("a[href]"):
        title = " ".join(a.stripped_strings).strip()
        href = a.get("href", "")
        if not title or not href:
            continue
        key = (title, href)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title,
            "start": "",  # No reliable time in rendered fallback without exact selectors
            "url": _u(base_url, href),
            "location": "",
        })

    return items
