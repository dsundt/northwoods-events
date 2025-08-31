# src/fetch.py
from typing import Optional
import os
import time
import requests

USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT") in ("1", "true", "True")

def fetch_text(
    url: str,
    headers: Optional[dict] = None,
    timeout: int = 30,
    use_playwright: Optional[bool] = None,
    **_ignore,  # tolerate stray kwargs like 'source'
) -> str:
    """Fetch text content from URL. Accepts stray kwargs to avoid breaking callers."""
    if use_playwright is None:
        use_playwright = USE_PLAYWRIGHT

    if not use_playwright:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        r.raise_for_status()
        return r.text

    # Minimal playwright path (avoids circular imports elsewhere)
    # Lazy import so environments without playwright still work
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.set_default_timeout(timeout * 1000)
            page.goto(url, wait_until="networkidle")
            # small settle
            time.sleep(0.3)
            return page.content()
        finally:
            browser.close()
