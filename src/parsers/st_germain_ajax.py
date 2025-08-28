# src/parsers/st_germain_ajax.py
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
from datetime import datetime

__all__ = ["parse_st_germain_ajax"]

def _text(el):
    return " ".join(el.stripped_strings) if el else ""

def parse_date(text):
    # Parse e.g. "Monday, September 1st, 2025" to ISO
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})", text)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
        except Exception:
            return ""
    return ""

def parse_st_germain_ajax(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    events = []

    # Find the "Local Events" tab content (panel-e11-e36 or similar)
    tab = soup.find("div", id=re.compile(r"panel-e11-e\d{2,}-?e?36"))
    if not tab:
        # Try fallback (panel-e11-e103 for mobile, etc.)
        tab = soup.find("div", id=re.compile(r"panel-e11-e\d{2,}-?e?103"))
    if not tab:
        return []

    # Each event is a link with h6 (title) and a span/subheadline (with date/location)
    for a in tab.find_all("a", class_="x-text-headline"):
        title = ""
        url = ""
        date_str = ""
        location = ""
        # Title
        h = a.find("h6")
        if h:
            title = _text(h)
        url = urljoin(base_url, a.get("href") or "")

        # Description/Date/Location in subheadline or <p> inside
        sub = a.find("span", class_="x-text-content-text-subheadline")
        if sub:
            # Try to find date (em/strong or just text)
            em = sub.find("em")
            strong = sub.find("strong")
            date_node = em or strong
            date_txt = _text(date_node) if date_node else _text(sub)
            date_str = parse_date(date_txt)
            # Try to get location (text after <br>)
            br = sub.find("br")
            if br and br.next_sibling:
                location = str(br.next_sibling).strip()
        # Defensive: ignore category links, empty events
        if not title or not url or not date_str:
            continue
        events.append({
            "title": title,
            "start": date_str,
            "url": url,
            "location": location
        })

    return events
