from bs4 import BeautifulSoup

def parse(html: str):
    """
    Parse TravelWisconsin widget (/events/widgetview) markup.
    Returns: list of dicts with title, url, date_text, venue_text
    """
    soup = BeautifulSoup(html or "", "lxml")
    items = []

    for el in soup.select("ul.event__list li.event__item"):
        a = el.find("a", href=True)
        if not a:
            continue

        title_el = el.select_one(".event-information h3, h3.location__header")
        title = (title_el.get_text(strip=True) if title_el else a.get_text(strip=True) or "").strip()

        url = (a.get("href") or "").strip()  # may be relative; main.py will absolutize with iframe base

        date_el = el.select_one(".status-update")
        date_text = (date_el.get_text(strip=True) if date_el else "").strip()

        venue_el = el.select_one(".event-location")
        venue_text = (venue_el.get_text(strip=True) if venue_el else "").strip()

        items.append({
            "title": title,
            "url": url,
            "date_text": date_text,   # e.g., 8/23/2025
            "venue_text": venue_text, # e.g., Rhinelander
            "iso_datetime": None,
            "iso_end": None,
        })
    return items
