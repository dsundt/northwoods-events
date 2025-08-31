import re, time
from typing import List, Dict
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
import dateparser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0; +https://github.com/dsundt/northwoods-events)"
}

def _get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

def _parse_event_page(html: str, base_url: str, tzname: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.find(["h1","h2"]) or {}).get_text(strip=True) if soup.find(["h1","h2"]) else None

    # common GrowthZone labels
    def grab(label):
        lab = soup.find(lambda tag: tag.name in ("h3","h4","strong") and label.lower() in tag.get_text(strip=True).lower())
        if not lab: return None
        # text could be sibling/parent wrapper
        texts = []
        for node in lab.parent.stripped_strings:
            texts.append(node)
        return " ".join(texts)

    # try specific blocks
    when_text = None
    for sel in ["div[id*='date']","div:contains('Date')","div:contains('Date/Time')"]:
        el = soup.select_one(sel)
        if el:
            when_text = " ".join(el.stripped_strings)
            break
    if not when_text:
        # generic fallback
        when_text = grab("date")

    loc_text = None
    for sel in ["div[id*='location']","div:contains('Location')"]:
        el = soup.select_one(sel)
        if el:
            loc_text = " ".join(el.stripped_strings)
            break
    if not loc_text:
        loc_text = grab("location")

    start_iso = end_iso = None
    if when_text:
        # examples: "Sunday Sep 1, 2025 10:00 AM - 2:00 PM"
        #           "Sep 6, 2025"
        parts = re.split(r"\bto\b|–|-|—", when_text)
        start_txt = parts[0].strip()
        end_txt = parts[1].strip() if len(parts) > 1 else None

        settings = {
            "TIMEZONE": tzname,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DAY_OF_MONTH": "first",
            "TO_TIMEZONE": tzname,
        }
        start_dt = dateparser.parse(start_txt, settings=settings)
        end_dt = dateparser.parse(end_txt, settings=settings) if end_txt else None
        start_iso = start_dt.isoformat() if start_dt else None
        end_iso = end_dt.isoformat() if end_dt else None

    return {
        "title": title or "Untitled",
        "start": start_iso,
        "end": end_iso,
        "location": (loc_text or "").strip() or None,
        "url": base_url,
    }

def scrape(calendar_url: str, name: str, tzname: str, limit: int = 150) -> List[Dict]:
    """
    Strategy:
      1) GET the month calendar HTML (server-rendered).
      2) Extract all event detail links (/events/details/…).
      3) Visit each detail page and parse Title/When/Location.
    """
    html = _get(calendar_url)
    soup = BeautifulSoup(html, "lxml")

    # collect detail links
    links = []
    for a in soup.select("a[href]"):
        href = a["href"]
        if "/events/details/" in href:
            links.append(urljoin(calendar_url, href))
    # de-dup and cap
    seen = []
    for u in links:
        if u not in seen:
            seen.append(u)
    links = seen[:limit]

    events: List[Dict] = []
    for i, url in enumerate(links):
        try:
            page = _get(url)
            ev = _parse_event_page(page, url, tzname)
            ev.update({"source": name, "source_kind": "GrowthZone", "source_url": calendar_url})
            # keep only items that at least have a date or a title
            if ev.get("title") or ev.get("start"):
                events.append(ev)
        except Exception:
            # be resilient; continue
            continue
        # very light politeness
        if (i + 1) % 5 == 0:
            time.sleep(0.5)

    return events
