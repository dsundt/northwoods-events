from __future__ import annotations
from typing import Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

def soupify(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")

def clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def abs_url(base: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    return urljoin(base, href)
