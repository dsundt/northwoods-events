# -*- coding: utf-8 -*-
"""
Fetch utilities with optional Playwright rendering.
"""

import os
import time
from typing import Tuple, Optional
from urllib.parse import urljoin
import requests

from . import render

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip() not in ("0", "false", "False", "")

def fetch(url: str, use_js: bool = False, wait_selector: Optional[str] = None, timeout: int = 30) -> Tuple[int, str]:
    """
    Returns (http_status, html_text). If `use_js` is True, uses Playwright to render.
    """
    if use_js:
        try:
            html = render.render_html(url, wait_selector=wait_selector, timeout_ms=timeout * 1000)
            # We'll pretend status 200 when render succeeds.
            return (200, html)
        except Exception as e:
            return (0, f"__RENDER_ERROR__ {e}")

    headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
    r = requests.get(url, headers=headers, timeout=timeout)
    return (r.status_code, r.text)
