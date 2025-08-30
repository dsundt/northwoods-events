# src/utils/filters.py
from __future__ import annotations
import re
from typing import Optional

_DATE_WORDS = r"(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t|tember)?|oct(ober)?|nov(ember)?|dec(ember)?)"
_DATE_TITLE_PATTERNS = [
    re.compile(rf"^\s*{_DATE_WORDS}\s+\d{{1,2}}(?:\s*,?\s*\d{{4}})?\s*$", re.I),
    re.compile(r"^\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?\s*$"),
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}\s*$"),
    re.compile(r"^\s*([A-Za-z]{3})\s+\d{1,2}(?:,?\s*\d{4})?\s*$"),  # Aug 12[, 2025]
    re.compile(r"^\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}/\d{1,2}\s*$", re.I),
]

def is_date_like_title(title: Optional[str]) -> bool:
    if not title:
        return False
    t = title.strip()
    if len(t) <= 3:
        return False
    # A single month like "August" is allowed
    if re.fullmatch(_DATE_WORDS, t, re.I):
        return False
    for pat in _DATE_TITLE_PATTERNS:
        if pat.match(t):
            return True
    # Mostly numbers/punct (e.g., "08.12.25")
    if re.fullmatch(r"[0-9\-/:\.\s@]+", t):
        return True
    return False

def is_recurring_text(text: Optional[str]) -> bool:
    return bool(text) and ("recurring" in text.lower())
