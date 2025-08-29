# -*- coding: utf-8 -*-
"""
Playwright HTML renderer (only used for JS-heavy sources).
"""

from contextlib import contextmanager
from urllib.parse import urlparse
from typing import Optional

def _bool_env(name: str, default: bool = False) -> bool:
    import os
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip() not in ("0", "false", "False", "")

@contextmanager
def _playwright():
    # lazy import so non-JS runs don't require playwright installed
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        yield pw
    finally:
        pw.stop()

def render_html(url: str, wait_selector: Optional[str] = None, timeout_ms: int = 30000) -> str:
    """
    Returns fully-rendered HTML for a URL using Playwright/Chromium.
    - Waits for network to go idle and (optionally) a `wait_selector`.
    """
    with _playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ))
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except Exception:
                    # If selector never appears, we still return what we have.
                    pass
            # Some Simpleview lists are infinite-scroll; try one scroll
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                pass
            html = page.content()
            return html
        finally:
            browser.close()
