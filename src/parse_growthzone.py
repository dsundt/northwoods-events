from bs4 import BeautifulSoup

def parse(html: str):
    """
    GrowthZone / ChamberMaster list/search pages.
    Return list of dicts: title, url, date_text, venue_text, iso_datetime?
    """
    soup = BeautifulSoup(html, "lxml")
    items = []

    # Common listing blocks
    candidates = soup.select(
        ".mn-content .listing, .cm-body .listing, .mn-list .listing, .listing, "
        ".mn-event, .mn-event-card, li.event, div.event"
    )

    for el in candidates:
        a = el.select_one('a[href*="/events/"]') or el.find("a", href=True)
        if not a:
            continue

        title = (a.get_text() or "").strip()
        url = (a.get("href") or "").strip()

        dt_el = el.select_one(".date, .mn-date, .gz-date, .cm-date, time[datetime], .event-date")
        if dt_el and dt_el.name == "time" and dt_el.get("datetime"):
            iso_dt = dt_el.get("datetime").strip()
            date_text = dt_el.get_text().strip()
        else:
            iso_dt = None
            date_text = (dt_el.get_text() if dt_el else "").strip()

        venue_el = el.select_one(".location, .mn-location, .cm-location, .gz-location, .event-location")
        venue_text = (venue_el.get_text() if venue_el else "").strip()

        items.append({
            "title": title,
            "url": url,
            "date_text": date_text,
            "venue_text": venue_text,
            "iso_datetime": iso_dt,
            "iso_end": None,
        })

    return items
