from __future__ import annotations
import os, re, json
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin
from bs4 import BeautifulSoup

__all__ = ["parse_simpleview"]

def _text(n) -> str:
    return " ".join(n.stripped_strings) if n else ""

def _as_list(x: Union[list, dict, None]) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

def _render_with_playwright(url: str, timeout_ms: int = 20000) -> Optional[str]:
    if os.getenv("USE_PLAYWRIGHT", "0") not in ("1","true","yes"):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    html = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        # Wait for anything that looks like event cards or schema
        page.wait_for_selector("script[type='application/ld+json'], [itemtype*='schema.org/Event'], article", timeout=timeout_ms)
        html = page.content()
        browser.close()
    return html

def _parse_json_ld_events(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for s in soup.find_all("script", {"type": "application/ld+json"}):
        raw = s.string or s.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            # sometimes multiple JSON objects are concatenated; try line-by-line
            chunks = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chunks.append(json.loads(line))
                except Exception:
                    pass
            data = chunks if chunks else None
        if not data:
            continue
        for obj in _as_list(data):
            # Some sites wrap with @graph
            graph = obj.get("@graph") if isinstance(obj, dict) else None
            candidates = _as_list(graph) if graph else _as_list(obj)
            for e in candidates:
                if not isinstance(e, dict):
                    continue
                typ = e.get("@type") or e.get("type")
                if isinstance(typ, list):
                    typ = next((t for t in typ if isinstance(t, str)), None)
                if not typ or "Event" not in str(typ):
                    continue
                name = (e.get("name") or "").strip()
                start = (e.get("startDate") or e.get("start_time") or "").strip()
                url = (e.get("url") or "").strip()
                # location -> name or address
                loc = ""
                loc_obj = e.get("location")
                if isinstance(loc_obj, dict):
                    loc = (loc_obj.get("name") or loc_obj.get("address") or "").strip()
                if name and start:
                    items.append({"title": name, "start": start, "url": url, "location": loc})
    return items

# microdata fallback
def _parse_microdata_events(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for scope in soup.select('[itemtype*="schema.org/Event"]'):
        name_el = scope.find(attrs={"itemprop": "name"})
        date_el = scope.find(attrs={"itemprop": "startDate"}) or scope.find("time")
        a = scope.find("a", href=True)
        title = (name_el.get("content") or _text(name_el)) if name_el else _text(scope.find(["h3","h2"]))
        start = date_el.get("content") if date_el and date_el.has_attr("content") else _text(date_el)
        if title and start:
            items.append({
                "title": title.strip(),
                "start": (start or "").strip(),
                "url": urljoin(base_url, a["href"]) if a else base_url,
                "location": ""
            })
    return items

# card fallback after JS render
def _parse_event_cards(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    # try a bunch of likely classes/containers
    cards = (
        soup.select(".event-card, .sv-event, .list-card, .event-listing article, .event-item")
        or soup.select("article")
    )
    for c in cards:
        a = c.find("a", href=True)
        title = _text(c.find(["h3","h2"])) or (a.get("title") if a and a.has_attr("title") else _text(a))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        # heuristics: avoid nav headings like "Events |" or "here"
        if title.lower() in {"events", "events |", "here", "annual events"}:
            continue
        # date/time visible?
        dt = c.find("time") or c.find(class_=re.compile(r"date|time", re.I))
        start = (dt.get("datetime") if dt and dt.has_attr("datetime") else _text(dt)).strip()
        if not start:
            # not an event card
            continue
        items.append({
            "title": title,
            "start": start,
            "url": urljoin(base_url, a["href"]) if a else base_url,
            "location": ""
        })
    return items

def parse_simpleview(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")

    # 1) JSON-LD events first (works even without JS if authors embed schema)
    items = _parse_json_ld_events(soup)
    if items:
        return items

    # 2) If nothing and Playwright allowed, render and retry JSON-LD / microdata / cards
    if os.getenv("USE_PLAYWRIGHT", "0") in ("1","true","yes"):
        rendered = _render_with_playwright(base_url)
        if rendered:
            soup = BeautifulSoup(rendered, "html.parser")
            items = _parse_json_ld_events(soup)
            if items:
                return items
            items = _parse_microdata_events(soup, base_url)
            if items:
                return items
            items = _parse_event_cards(soup, base_url)
            if items:
                return items

    # 3) Last resort: try microdata in static HTML
    items = _parse_microdata_events(soup, base_url)
    return items
