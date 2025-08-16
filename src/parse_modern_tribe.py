import json
from bs4 import BeautifulSoup

def _jsonld_events(soup):
    out = []
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        # sometimes it's a dict with @graph, sometimes a list
        candidates = []
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                candidates = data["@graph"]
            else:
                candidates = [data]
        elif isinstance(data, list):
            candidates = data
        for node in candidates:
            if not isinstance(node, dict):
                continue
            if node.get("@type") in ("Event", ["Event"]):
                name = (node.get("name") or "").strip()
                url = (node.get("url") or "").strip()
                startDate = node.get("startDate") or node.get("startTime")
                endDate = node.get("endDate") or node.get("endTime")
                venue = ""
                loc = node.get("location")
                if isinstance(loc, dict):
                    venue = (loc.get("name") or "") or (loc.get("address") or "")
                out.append({
                    "title": name,
                    "url": url,
                    "date_text": "",             # not needed if iso present
                    "venue_text": venue.strip(),
                    "iso_datetime": startDate or None,
                    "iso_end": endDate or None
                })
    return out

def parse(html):
    """
    Return list of dicts:
      {title, url, date_text, venue_text, iso_datetime?, iso_end?}
    Supports The Events Calendar (Modern Tribe) list and newer views.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []

    # 1) Try known list selectors (multiple generations)
    selectors = [
        ".tribe-events-calendar-list__event",
        "article.tribe_events",
        ".type-tribe_events",
        ".tribe-events-calendar__list-item",
        ".tribe-events-calendar-day__event",
        ".tribe-common-g-row .tribe-events-calendar-latest__event"
    ]
    containers = []
    for sel in selectors:
        containers = soup.select(sel)
        if containers:
            break

    for el in containers:
        a = el.select_one(".tribe-events-calendar-list__event-title a, .tribe-event-title a, a.tribe-events-calendar-list__event-title-link, a.tribe-events-calendar-event-title")
        if not a:
            a = el.find("a")
        if not a:
            continue
        title = (a.get_text() or "").strip()
        url = (a.get("href") or "").strip()

        # Prefer <time datetime="..."> if present
        start_iso = None
        end_iso = None
        time_els = el.select("time[datetime]")
        if time_els:
            start_iso = time_els[0].get("datetime") or None
            if len(time_els) > 1:
                end_iso = time_els[-1].get("datetime") or None

        # Visible date text (fallback)
        dt_el = el.select_one(".tribe-events-calendar-list__event-datetime, .tribe-events-c-small-cta__date, .tribe-event-date-start, .tribe-event-time, .tribe-events-calendar-event-datetime")
        date_text = (dt_el.get_text() if dt_el else "").strip()

        venue_el = el.select_one(".tribe-events-calendar-list__event-venue, .tribe-events-venue, .tribe-venue, .tribe-address, .tribe-events-calendar-event-venue")
        venue_text = (venue_el.get_text() if venue_el else "").strip()

        items.append({
            "title": title,
            "url": url,
            "date_text": date_text,
            "venue_text": venue_text,
            "iso_datetime": start_iso,
            "iso_end": end_iso
        })

    # 2) If nothing found, try JSON-LD embedded events (very common)
    if not items:
        items = _jsonld_events(soup)

    return items
