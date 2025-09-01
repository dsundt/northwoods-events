# src/fetch.py
import os
import time
import contextlib
from typing import Optional, Dict

import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Broadened defaults so the page reliably "settles" before we scrape.
KIND_DEFAULT_WAIT: Dict[str, Optional[str]] = {
    "modern_tribe": ".tribe-events, .tec-events, .tribe-common, [data-view*='events']",
    "growthzone": ".gzec-calendar, .gz-events, .event-list, #EventList, .calendar",
    "simpleview": ".event-listing, .event-card, .listing, .sv-events, [data-results], .results",
    "ics": None,
}

REQ_TIMEOUT = int(os.environ.get("REQ_TIMEOUT", "25"))
PLAYWRIGHT_TIMEOUT_MS = int(os.environ.get("PLAYWRIGHT_TIMEOUT_MS", "20000"))
USE_PLAYWRIGHT = str(os.environ.get("USE_PLAYWRIGHT", "0")).strip() in {"1", "true", "yes"}


def _requests_get(url: str) -> str:
    r = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"},
        timeout=REQ_TIMEOUT,
    )
    r.raise_for_status()
    return r.text


def _playwright_get(url: str, wait_for: Optional[str]) -> str:
    # Import here so local devs without playwright can still import this module.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            context = browser.new_context(user_agent=USER_AGENT, locale="en-US")
            page = context.new_page()
            page.set_default_timeout(PLAYWRIGHT_TIMEOUT_MS)
            page.goto(url, wait_until="domcontentloaded")
            if wait_for:
                with contextlib.suppress(Exception):
                    page.wait_for_selector(wait_for, state="attached")
                    # Give dynamic lists a moment to hydrate
                    time.sleep(0.5)
            html = page.content()
        finally:
            browser.close()
    return html


def fetch_html(url: str, source: Optional[dict] = None, wait_selector: Optional[str] = None) -> str:
    """
    Fetch HTML using Playwright when enabled (dynamic) or requests (static).
    `source` may include {"kind": "..."} to pick a default wait selector.
    """
    if wait_selector is None and source and source.get("kind"):
        wait_selector = KIND_DEFAULT_WAIT.get(source["kind"])

    if USE_PLAYWRIGHT and wait_selector is not None:
        with contextlib.suppress(Exception):
            return _playwright_get(url, wait_selector)

    # Fallback to plain requests
    return _requests_get(url)
