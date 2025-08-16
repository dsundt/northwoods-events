from bs4 import BeautifulSoup

def parse(html):
    """
    GrowthZone/ChamberMaster list/search pages
    Returns list of dicts: {title, url, date_text, venue_text}
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    # target generic listing blocks
    for el in soup.select(".mn-content .listing, .cm-body .listing, .mn-list .listing, .listing"):
        a = el.select_one('a[href*="/events/"]')
        if not a:
            continue
        title = (a.get_text() or "").strip()
        url = a.get("href", "").strip()
        # make absolute if needed
        if url.startswith("/"):
            # derive origin from any canonical/base or fall back to domain you called
            base = (soup.find("base") or {}).get("href") or ""
            # if no <base>, caller should absolutize using requests URL
        date_el = el.select_one(".date, .mn-date, .gz-date, .cm-date")
        date_text = (date_el.get_text() if date_el else "").strip()
        venue_el = el.select_one(".location, .mn-location, .cm-location, .gz-location")
        venue_text = (venue_el.get_text() if venue_el else "").strip()
        items.append({"title": title, "url": url, "date_text": date_text, "venue_text": venue_text})
    return items
