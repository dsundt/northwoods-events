from bs4 import BeautifulSoup

def parse(html):
    """
    GrowthZone/ChamberMaster list/search pages
    Returns list of dicts: {title, url, date_text, venue_text, iso_datetime?}
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    for el in soup.select(".mn-content .listing, .cm-body .listing, .mn-list .listing, .listing"):
        a = el.select_one('a[href*="/events/"]')
        if not a:
            continue
        title = (a.get_text() or "").strip()
        url = a.get("href", "").strip()

        # date blocks vary
        dt_el = el.select_one(".date, .mn-date, .gz-date, .cm-date, time[datetime]")
        iso_dt = dt_el.get("datetime").strip() if dt_el and dt_el.name == "time" and dt_el.get("datetime") else None
        date_text = (dt_el.get_text() if dt_el else "").strip()

        venue_el = el.select_one(".location, .mn-location, .cm-location, .gz-location")
        venue_text = (venue_el.get_text() if venue_el else "").strip()
        items.append({"title": title, "url": url, "date_text": date_text, "venue_text": venue_text, "iso_datetime": iso_dt})
    return items
