from __future__ import annotations
import os, time, contextlib
import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) NorthwoodsEventsBot/1.0 (+https://github.com/)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def should_use_playwright(parser_kind: str, url: str) -> bool:
    if os.getenv("USE_PLAYWRIGHT", "") not in ("1", "true", "yes"):
        return False
    pk = (parser_kind or "").lower()
    if pk in ("simpleview", "st_germain_ajax"):
        return True
    # fallback heuristic for obviously client-rendered pages:
    return any(hint in url for hint in ("/events/", "/events-calendar", "/festivals-events"))

def fetch_html(
    url: str,
    use_playwright: bool = False,
    wait_selector: str | None = None,
    wait_time_ms: int = 2000,
    timeout_ms: int = 30000,
) -> tuple[int | None, str]:
    """
    Returns (status_code, html). status_code is None when Playwright path is used.
    """
    if use_playwright:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            # Playwright not installed; fallback to requests
            return _fetch_requests(url)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            if wait_selector:
                with contextlib.suppress(Exception):
                    page.wait_for_selector(wait_selector, state="attached", timeout=timeout_ms)
            else:
                with contextlib.suppress(Exception):
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
            if wait_time_ms > 0:
                time.sleep(wait_time_ms / 1000.0)
            content = page.content()
            ctx.close()
            browser.close()
            return (None, content)

    # default: requests
    return _fetch_requests(url)

def _fetch_requests(url: str) -> tuple[int, str]:
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    return (r.status_code, r.text)
