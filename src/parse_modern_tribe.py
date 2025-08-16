from bs4 import BeautifulSoup

def parse(html):
    """
    Returns list of dicts: {title, url, date_text, venue_text, iso_datetime?}
    Works on Modern Tribe LIST view (?eventDisplay=list)
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    containers = soup.select(".tribe-events-calendar-list__event, article.tribe_events, .type-tribe_events")
    for el in containers:
        a = el.select_one(".tribe-events-calendar-list__event-title a, .tribe-event-title a")
        if not a:
            continue
        title = (a.get_text() or "").strip()
        url = a.get("href", "").strip()

        # Prefer <time datetime="...">
        time_el = el.select_one("time[datetime]")
        iso_dt = time_el.get("datetime").strip() if time_el and time_el.get("datetime") else None

        # Fallback: visible date text
        dt_el = el.select_one(".tribe-events-calendar-list__event-datetime, .tribe-events-c-small-cta__date, .tribe-event-date-start, .tribe-event-time")
        date_text = (dt_el.get_text() if dt_el else "").strip()

        venue_el = el.select_one(".tribe-events-calendar-list__event-venue, .tribe-events-venue, .tribe-venue, .tribe-address")
        venue_text = (venue_el.get_text() if venue_el else "").strip()

        items.append({"title": title, "url": url, "date_text": date_text, "venue_text": venue_text, "iso_datetime": iso_dt})
    return items
