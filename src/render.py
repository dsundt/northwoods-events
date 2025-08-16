import os
from contextlib import asynccontextmanager
from playwright.sync_api import sync_playwright

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "(compatible; NorthwoodsBot/1.0; +https://github.com/dsundt/northwoods-events)"
)

def render_url(url: str, wait_selector: str | None = None, timeout_ms: int = 20000) -> tuple[str, str]:
    """
    Returns (html, final_url). Uses Chromium headless to render JS sites.
    Optionally waits for a CSS selector before dumping HTML.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"
        ])
        ctx = browser.new_context(user_agent=UA, viewport={"width":1280,"height":2000})
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        page.goto(url, wait_until="domcontentloaded")
        # if page has a consent banner, try to accept common buttons quickly (best-effort)
        for sel in ["button#onetrust-accept-btn-handler", "button[aria-label='Accept all']", "button:has-text('Accept')"]:
            try:
                page.locator(sel).click(timeout=1500)
                break
            except Exception:
                pass
        # wait for activity/network to settle
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=4000)
            except Exception:
                pass
        html = page.content()
        final_url = page.url
        ctx.close()
        browser.close()
    return html, final_url
