from __future__ import annotations
from urllib.parse import urljoin

def clean(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.split())

def absolutize(base: str, href: str | None) -> str:
    if not href:
        return base
    return urljoin(base, href)
