import os, re, asyncio
from typing import Tuple

# returns (html, final_url) or raises
def _playwright_fetch(url: str, wait_for: str | None = None) -> Tuple[str, str]:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = browser.new_context(java_script_enabled=True)
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=15000)
                except Exception:
                    # ignore; some sites won't match but content is there
                    pass
            html = page.content()
            final_url = page.url
            return html, final_url
        finally:
            browser.close()

def _requests_fetch(url: str) -> Tuple[str, str]:
    import requests
    headers = {
        "User-Agent": os.environ.get("HTTP_USER_AGENT","Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
    }
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.text, r.url

def fetch_html(url: str, wait_for: str | None = None) -> Tuple[str, str]:
    """
    Fetch HTML content, preferring Playwright when USE_PLAYWRIGHT=1.
    """
    use_pw = os.environ.get("USE_PLAYWRIGHT","").strip() == "1"
    if use_pw:
        return _playwright_fetch(url, wait_for=wait_for)
    return _requests_fetch(url)

def fetch_text(url: str) -> Tuple[str, str]:
    """
    Fetch plain text content (used for ICS). Uses requests only.
    """
    import requests
    headers = {
        "User-Agent": os.environ.get("HTTP_USER_AGENT","Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
    }
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.text, r.url
