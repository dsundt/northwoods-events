# fetch.py
from __future__ import annotations

import os
import time
import random
from typing import Optional
from contextlib import contextmanager

import requests

DEFAULT_TIMEOUT_MS = 25000
DEFAULT_WAIT_MS = 800

# Per-kind default selectors that usually indicate DOM is hydrated
KIND_DEFAULT_WAIT = {
    "modern_tribe": ".tribe-events .tribe-events-calendar-list, .tribe-events-view, .tec-events",
    "simpleview": ".card, .event, .events-list, .listing-items",
    "growthzone": ".event-list, .events, .EventList, .eventItem",
    "micronet_ajax": ".cm-event, .event-item, #communityCalendar, .calendarEventList",
    "ai1ec": ".ai1ec-agenda-view, .ai1ec-month-view, .ai1ec-week-view",
    "travelwi": ".event-list, .event, .listing",
    "ics": None,
    "municipal": ".ai1ec-agenda-view, .ai1ec-month-view, .ai1ec-week-view",
    "squarespace": "ul.eventlist, section.eventlist, .sqs-block-calendar, .events, .events-list",
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

def _sleep_ms(ms: int) -> None:
    if ms and ms > 0:
        time.sleep(ms / 1000.0)

def _requests_fetch(url: str, timeout_ms: int) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    resp = requests.get(url, headers=headers, timeout=timeout_ms / 1000.0)
    resp.raise_for_status()
    return resp.text

@contextmanager
def _playwright_context():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox","--disable-gpu"], headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
            device_scale_factor=1
        )
        try:
            yield context
        finally:
            context.close()
            browser.close()

def fetch_html(url: str, *, source: Optional[dict] = None) -> str:
    """
    Fetch HTML for a URL.
    Uses Playwright when USE_PLAYWRIGHT=1 or source['force_browser']=True,
    else falls back to requests.
    Honors source['wait_selector'], source['wait_ms'], source['timeout_ms'],
    and optional source['scroll_steps'] / source['scroll_delay_ms'].
    Retries transient failures.
    """
    source = source or {}
    kind = (source.get("kind") or "").strip().lower() or None

    wait_selector = source.get("wait_selector")
    if not wait_selector and kind:
        wait_selector = KIND_DEFAULT_WAIT.get(kind)

    timeout_ms = int(source.get("timeout_ms") or DEFAULT_TIMEOUT_MS)
    wait_ms = int(source.get("wait_ms") or DEFAULT_WAIT_MS)

    scroll_steps = int(source.get("scroll_steps") or 0)
    scroll_delay_ms = int(source.get("scroll_delay_ms") or 350)

    use_playwright = (
        str(source.get("force_browser") or "").lower() in ("1", "true", "yes")
        or str(os.environ.get("USE_PLAYWRIGHT") or "").lower() in ("1", "true", "yes")
    )

    # Simple retry policy
    attempts = int(source.get("retries") or 3)
    backoff_base = float(source.get("retry_backoff") or 0.6)

    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            if use_playwright:
                with _playwright_context() as context:
                    page = context.new_page()
                    page.set_default_timeout(timeout_ms)
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

                    if wait_selector:
                        page.wait_for_selector(wait_selector, timeout=timeout_ms)
                    # let XHR settle; then optional scroll to force lazy lists
                    page.wait_for_load_state("networkidle")
                    _sleep_ms(wait_ms)

                    if scroll_steps > 0:
                        for _ in range(scroll_steps):
                            page.mouse.wheel(0, 20000)
                            page.wait_for_load_state("networkidle")
                            _sleep_ms(scroll_delay_ms)

                    return page.content()
            else:
                return _requests_fetch(url, timeout_ms)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt >= attempts:
                break
            # backoff + jitter
            delay = backoff_base * attempt + random.random() * 0.2
            time.sleep(delay)

    # If browser path failed, try requests as a last resort
    if use_playwright:
        try:
            return _requests_fetch(url, timeout_ms)
        except Exception:
            pass
    if last_exc:
        raise last_exc
    raise RuntimeError("fetch_html failed with unknown error")
