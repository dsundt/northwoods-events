from typing import Optional
import os, time, sys
import requests

# Enable Playwright globally via env or per-call via use_playwright=True
USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT") in ("1", "true", "True")

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

def _requests_text(url: str, headers: Optional[dict], timeout: int, tries: int = 3) -> Optional[str]:
    h = dict(_DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=h, timeout=timeout, allow_redirects=True)
            # stderr breadcrumbs for CI logs
            print(f"[fetch] GET {url} → {r.status_code} ({len(r.content)} bytes)", file=sys.stderr)
            if r.status_code == 200:
                return r.text
            last = r
            time.sleep(0.4 * (i + 1))
        except Exception as e:
            print(f"[fetch] requests error try {i+1}: {e}", file=sys.stderr)
            time.sleep(0.4 * (i + 1))
    return None

def _playwright_html(url: str, timeout: int, headers: Optional[dict]) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = browser.new_context(
                user_agent=_DEFAULT_HEADERS["User-Agent"],
                locale="en-US",
                extra_http_headers=headers or {},
            )
            page = context.new_page()
            page.set_default_timeout(timeout * 1000)
            page.goto(url, wait_until="networkidle")
            time.sleep(0.25)
            html = page.content()
            print(f"[fetch] PW GET {url} → {len(html)} chars", file=sys.stderr)
            return html
        finally:
            browser.close()

def fetch_text(
    url: str,
    headers: Optional[dict] = None,
    timeout: int = 30,
    use_playwright: Optional[bool] = None,
    **_ignore,  # tolerate stray kwargs like 'source', etc.
) -> str:
    """
    Fetch HTML/text. If use_playwright is True (or USE_PLAYWRIGHT env is set), use Playwright.
    Otherwise try requests with retries and a realistic UA; if content is missing or tiny,
    fall back to Playwright automatically (when USE_PLAYWRIGHT env is enabled).
    """
    if use_playwright is None:
        use_playwright = USE_PLAYWRIGHT

    # Forced Playwright
    if use_playwright:
        return _playwright_html(url, timeout, headers)

    # Try requests first
    txt = _requests_text(url, headers, timeout)
    # Heuristic: if we got nothing or extremely small content, fall back (when allowed)
    if (txt is None or len(txt) < 512) and USE_PLAYWRIGHT:
        print("[fetch] falling back to Playwright due to empty/small response", file=sys.stderr)
        return _playwright_html(url, timeout, headers)

    if txt is None:
        # As a last resort, return an empty string so callers don't crash
        return ""
    return txt

def fetch_html(*args, **kwargs) -> str:
    """Backward-compatible alias used by some parsers."""
    return fetch_text(*args, **kwargs)
