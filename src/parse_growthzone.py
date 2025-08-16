from bs4 import BeautifulSoup

def parse(html: str):
    """
    GrowthZone / ChamberMaster list or calendar pages.
    Returns list of dicts: title, url, date_text, venue_text, iso_datetime?, iso_end?
    """
    soup = BeautifulSoup(html, "lxml")
    items = []

    # Candidates: various layouts GrowthZone uses
    wrappers = soup.select(
        ".mn-content .listing, .cm-body .listing, .mn-list .listing, .listing,"
        ".mn-event, .mn-event-card, li.event, div.event, .mn-calendar .mn-CalendarItem"
    )

    # If we didn't see generic wrappers, fall back to any link into an event details page
    if not wrappers:
        for a in soup.select('a[href*="/events/details/"], a[href*="/events/Details/"]'):
            parent = a.find_parent(["li","div","article"]) or a
            wrappers.append(parent)

    for el in wrappers:
        a = el.select_one('a[href*="/events/details/"], a[href*="/events/Details/"], a[href*="/events/"]')
        if not a:
            continue

        title = (a.get_text(strip=True) or "").strip()
        url = (a.get("href") or "").strip()

        # date/time text
        dt_el = (
            el.select_one("time[datetime]") or
            el.select_one(".date, .mn-date, .gz-date, .cm-date, .event-date, .mn-CalendarDate") or
            el
        )
        if dt_el and getattr(dt_el, "name", "") == "time" and dt_el.get("datetime"):
            iso_dt = dt_el.get("datetime").strip()
            date_text = dt_el.get_text(strip=True)
        else:
            iso_dt = None
            date_text = (dt_el.get_text(strip=True) if dt_el else "")

        # location/venue
        venue_el = el.select_one(".location, .mn-location, .cm-location, .gz-location, .event-location, .mn-CalendarLocation")
        venue_text = (venue_el.get_text(strip=True) if venue_el else "")

        items.append({
            "title": title,
            "url": url,
            "date_text": date_text,
            "venue_text": venue_text,
            "iso_datetime": iso_dt,
            "iso_end": None,
        })

    return items
