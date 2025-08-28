# src/utils/text.py
from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag
import re

_WS = re.compile(r"\s+")

def _text(node_or_html: str | Tag | BeautifulSoup) -> str:
    """
    Tiny helper that returns normalized visible text.
    Accepts HTML string, BeautifulSoup/Tag, or NavigableString.
    """
    if isinstance(node_or_html, (Tag, BeautifulSoup)):
        raw = node_or_html.get_text(" ", strip=True)
    elif isinstance(node_or_html, NavigableString):
        raw = str(node_or_html)
    else:
        # assume raw html
        soup = BeautifulSoup(node_or_html, "html.parser")
        raw = soup.get_text(" ", strip=True)

    # collapse whitespace
    return _WS.sub(" ", raw).strip()
