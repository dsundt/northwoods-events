from __future__ import annotations
from typing import Optional, Tuple
import requests
from urllib.parse import urlparse, urlunparse, urljoin
import logging

DEFAULT_TIMEOUT = 30

def fetch_text(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> Tuple[int, str]:
    """Basic HTTP GET fetch (no JS). Returns (status_code, text)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0)"
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    return r.status_code, r.text

def _have_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False

def fetch_rendered(url: str, *, wait_selector: Optional[str] = None, timeout_ms: int = 20000) -> str:
    """
    Render the page with Playwright (Chromium) and return fully rendered HTML.
    Requires 'playwright' installed and 'playwright install chromium' done on the runner.
    """
    if not _have_playwright():
        logging.warning("Playwright not installed; cannot render JS for %s", url)
        return ""

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            except Exception:
                # continue anyway; page.content() may still contain useful HTML
                pass
        html = page.content()
        browser.close()
        return html

def site_root(url: str) -> str:
    """Return scheme://host/ from any URL."""
    pr = urlparse(url)
    return urlunparse((pr.scheme, pr.netloc, "", "", "", ""))

def try_wp_tec_json(url: str, *, days_back: int = 120, days_forward: int = 365) -> Optional[dict]:
    """
    Attempt WordPress 'The Events Calendar' REST: /wp-json/tribe/events/v1/events
    Returns parsed JSON dict on success, else None.
    """
    root = site_root(url)
    endpoint = urljoin(root, "/wp-json/tribe/events/v1/events")
    params = {
        "per_page": 50,
        # TEC accepts ISO strings; keep loose defaults. If needed, add exact date windows.
        # "start_date": "...", "end_date": "..."
    }
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0)"}
    try:
        r = requests.get(endpoint, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200 and r.headers.get("content-type", "").lower().startswith("application/json"):
            return r.json()
    except Exception as e:
        logging.info("TEC JSON fetch failed for %s: %s", endpoint, e)
    return None
