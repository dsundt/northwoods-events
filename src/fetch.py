# fetch.py
from __future__ import annotations

import os
import re
import contextlib
from pathlib import Path
from typing import Optional

import requests

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "") == "1"
DEFAULT_TIMEOUT_MS = 20000  # 20s


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "page"


def _maybe_save_snapshot(html: str, source: dict) -> None:
    """
    Best-effort HTML snapshot for debugging. Writes to state/snapshots if it exists.
    Never raises.
    """
    try:
        outdir = Path("state/snapshots")
        if not outdir.is_dir():
            return
        name = source.get("name") or source.get("url") or "page"
        fp = outdir / f"{_slug(str(name))}.html"
        fp.write_text(html, encoding="utf-8")
    except Exception:
        pass


def fetch_html(
    url: str,
    *,
    source: Optional[dict] = None,
    wait_selector: Optional[str] = None,
    wait_ms: Optional[int] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> str:
    """
    Fetch HTML using requests by default; if USE_PLAYWRIGHT=1, use Playwright and
    wait for client-rendered content.

    Priority for wait hints:
      explicit arg > source['wait_selector'/'wait_ms'] > none
    """
    # Resolve wait hints from source if not provided explicitly
    if source and wait_selector is None:
        wait_selector = source.get("wait_selector")
    if source and wait_ms is None:
        try:
            v = source.get("wait_ms")
            wait_ms = int(v) if v is not None else None
        except Exception:
            wait_ms = None

    if not USE_PLAYWRIGHT:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        resp.raise_for_status()
        return resp.text

    # Playwright path (sync API)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context(
                user_agent=UA,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
            )
            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            # Navigate and perform conservative load waits.
            page.goto(url, wait_until="domcontentloaded")
            with contextlib.suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=max(1000, timeout_ms // 2))

            # If the caller knows a container that indicates "content is ready", wait for it.
            if wait_selector:
                with contextlib.suppress(Exception):
                    page.wait_for_selector(wait_selector, state="attached", timeout=timeout_ms)

            # Optional additional grace period for slow hydrations.
            if wait_ms and wait_ms > 0:
                with contextlib.suppress(Exception):
                    page.wait_for_timeout(int(wait_ms))

            html = page.content()
            if source:
                _maybe_save_snapshot(html, source)
            return html
        finally:
            with contextlib.suppress(Exception):
                context.close()
            with contextlib.suppress(Exception):
                browser.close()
