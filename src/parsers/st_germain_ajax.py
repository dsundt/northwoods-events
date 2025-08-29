from __future__ import annotations
import os
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _try_playwright(url: str) -> str | None:
    if os.getenv("USE_PLAYWRIGHT") != "1":
        return None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            # Wait for any event list to appear
            page.wait_for_timeout(1500)
            html = page.content()
            ctx.close()
            browser.close()
            return html
    except Exception:
        return None

def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict[str, Any]]:
    # If Playwright is enabled, re-render
    rendered = _try_playwright(base_url)
    if rendered:
        html = rendered

    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # St Germain site: event entries appear as links under their calendar listing
    # Be conservative: pick content inside main and find anchors to /events/<slug>/
    main = soup.find("main") or soup
    for a in main.find_all("a", href=True):
        href = a["href"]
        if "/events/" not in href:
            continue
        title = _text(a).strip()
        if not title:
            continue
        # Try to find nearby date text
        container = a.find_parent(["li", "article", "div"]) or a
        date_bits = []
        for cls in ("date", "time", "tribe-event-date", "tribe-event-date-start"):
            el = container.find(class_=cls)
            if el:
                date_bits.append(_text(el))
        start = " ".join(date_bits).strip()

        items.append({
            "title": title,
            "start": start,
            "url": urljoin(base_url, href),
            "location": "",
        })

    # Deduplicate by URL
    seen = set()
    deduped = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        deduped.append(it)

    return deduped[:200]
