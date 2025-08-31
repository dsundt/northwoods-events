# src/fetch.py
from typing import Optional
import os
import time
import requests

# Honor CI flag; can still be overridden per-call
USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT") in ("1", "true", "True")


def fetch_text(
    url: str,
    headers: Optional[dict] = None,
    timeout: int = 30,
    use_playwright: Optional[bool] = None,
    **_ignore,  # tolerate stray kwargs like 'source', 'referer', etc.
) -> str:
    """
    Fetch the HTML/text at a URL. Uses requests by default; can use Playwright when
    use_playwright=True (or env USE_PLAYWRIGHT=1). Extra kwargs are ignored so callers
    passing unexpected params won't crash.
    """
    if use_playwright is None:
        use_playwright = USE_PLAYWRIGHT

    if not use_playwright:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        r.raise_for_status()
        return r.text

    # Lazy import so environments without playwright still work
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            if headers:
                page.set_extra_http_headers(headers)
            page.set_default_timeout(timeout * 1000)
            page.goto(url, wait_until="networkidle")
            # brief settle for late JS
            time.sleep(0.25)
            return page.content()
        finally:
            browser.close()


def fetch_html(*args, **kwargs) -> str:
    """
    Backward-compatible alias used by some parsers.
    Same signature/behavior as fetch_text.
    """
    return fetch_text(*args, **kwargs)
