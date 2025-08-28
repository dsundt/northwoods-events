from __future__ import annotations
import os, re, json
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

__all__ = ["parse_st_germain_ajax"]

ORDINAL = re.compile(r"(\d+)(st|nd|rd|th)", re.I)

MONTHS = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12
}

DATE_LINE = re.compile(
    r"(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(?P<day>\d{1,2}(?:st|nd|rd|th)?)"
    r"(?:,?\s*(?P<year>\d{4}))?",
    re.I
)

TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm)\b", re.I)

def _text(n) -> str:
    return " ".join(n.stripped_strings) if n else ""

def _strip_ord(x: str) -> str:
    return ORDINAL.sub(lambda m: m.group(1), x)

def _parse_datetime(line: str) -> Optional[str]:
    # Examples:
    # "Monday, September 1st, 2025"
    # "Saturday, September 20th, 2025 10:00 am"
    m = DATE_LINE.search(line or "")
    if not m:
        return None
    month = MONTHS[m.group("month").lower()]
    day = int(_strip_ord(m.group("day")))
    year = int(m.group("year") or "0") or _infer_year(month, day)
    # time optional
    t = TIME_RE.search(line)
    if t:
        h = int(t.group(1)) % 12
        mnt = int(t.group(2))
        if t.group(3).lower() == "pm": h += 12
        return f"{year:04d}-{month:02d}-{day:02d}T{h:02d}:{mnt:02d}:00"
    return f"{year:04d}-{month:02d}-{day:02d}T00:00:00"

def _infer_year(m: int, d: int) -> int:
    from datetime import date
    today = date.today()
    y = today.year
    # crude rollover: if month/day already far in past, push to next year
    try:
        from datetime import date as dte
        if (dte(y, m, d) - today).days < -300:
            return y + 1
    except Exception:
        pass
    return y

def _render_with_playwright(url: str, timeout_ms: int = 20000) -> Optional[str]:
    if os.getenv("USE_PLAYWRIGHT", "0") not in ("1", "true", "yes"):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    html = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        # Wait for any Micronet/ChamberMaster event container
        sel = "article, .cm-events, .cm-event, .event, .events-list, [data-testid*=event]"
        page.wait_for_selector(sel, timeout=timeout_ms)
        html = page.content()
        browser.close()
    return html

def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict[str, Any]]:
    # If static HTML shows no events (Micronet loads via JS), try rendering
    soup = BeautifulSoup(html, "html.parser")
    has_dynamic = not soup.select("article, .cm-event, .cm-events, .events-list")
    if has_dynamic:
        rendered = _render_with_playwright(base_url)
        if rendered:
            soup = BeautifulSoup(rendered, "html.parser")

    items: List[Dict[str, Any]] = []
    # Try a few common patterns after JS render
    cards = (
        soup.select(".cm-event, .cm-events .event, .events-list article")
        or soup.select("article")
    )
    for c in cards:
        a = c.find("a", href=True)
        url = urljoin(base_url, a["href"]) if a else base_url
        title = _text(c.find(["h3","h2"])) or _text(a)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        # Look for a date line near the title
        context = _text(c)
        start = _parse_datetime(context) or _parse_datetime(title)
        if not start:
            # skip empty shells
            continue
        loc = ""
        loc_el = c.find(class_=re.compile("location|venue", re.I))
        if loc_el:
            loc = _text(loc_el)
        items.append({"title": title, "start": start, "url": url, "location": loc})
    return items
