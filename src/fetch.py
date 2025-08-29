# src/fetch.py
from __future__ import annotations

import os
import time
import random
from contextlib import contextmanager
from typing import Optional

import requests

DEFAULT_TIMEOUT_MS = 25000
DEFAULT_WAIT_MS = 800

KIND_DEFAULT_WAIT = {
    "modern_tribe": ".tribe-events, .tec-events, .tribe-common",
    "simpleview": ".event-listing, .lv-event, .event",
    "growthzone": ".listing, .mn-event, .mn-CalendarItem",
    "ai1ec": ".ai1ec-event, .eventlist, .events",
}

def _sleep_ms(ms: int):
    time.sleep(ms / 1000.0)

@contextmanager
def _playwright_context():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = browser.new_context()
            yield ctx
        finally:
            browser.close()

def fetch_text(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str:
    resp = requests.get(url, timeout=timeout_ms / 1000.0, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.text

def fetch_html(url: str, source: Optional[dict] = None) -> str:
    """Render with Playwright when USE_PLAYWRIGHT=1 else plain requests."""
    use_pw = os.environ.get("USE_PLAYWRIGHT", "").strip() == "1"
    wait_selector = None
    if source:
        wait_selector = source.get("wait_selector")
        if not wait_selector:
            wait_selector = KIND_DEFAULT_WAIT.get((source.get("kind") or "").lower())

    if not use_pw:
        return fetch_text(url)

    try:
        with _playwright_context() as ctx:
            page = ctx.new_page()
            to = int(source.get("timeout_ms", DEFAULT_TIMEOUT_MS)) if source else DEFAULT_TIMEOUT_MS
            page.set_default_timeout(to)
            page.goto(url, timeout=to, wait_until="domcontentloaded")
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=to)
            page.wait_for_load_state("networkidle")
            _sleep_ms(int(source.get("wait_ms", DEFAULT_WAIT_MS)) if source else DEFAULT_WAIT_MS)
            # force a small scroll to trigger lazy lists
            page.mouse.wheel(0, 4000)
            page.wait_for_load_state("networkidle")
            return page.content()
    except Exception:
        # graceful fallback
        return fetch_text(url)
