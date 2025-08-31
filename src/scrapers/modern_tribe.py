from typing import List, Dict
from urllib.parse import urlparse
import requests, datetime as dt
import dateparser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthwoodsEventsBot/1.0; +https://github.com/dsundt/northwoods-events)"
}

def site_root(u: str) -> str:
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}"

def scrape(base_url: str, name: str, tzname: str, limit: int = 150) -> List[Dict]:
    """
    Primary: use The Events Calendar REST API
      {site}/wp-json/tribe/events/v1/events?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&per_page=N
    Fallback: none (API is very consistent across sites using the plugin).
    """
    root = site_root(base_url)
    api = f"{root}/wp-json/tribe/events/v1/events"

    today = dt.date.today()
    start = today - dt.timedelta(days=7)
    end = today + dt.timedelta(days=365)

    params = {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "per_page": min(300, limit),
    }

    r = requests.get(api, params=params, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return []
    data = r.json()
    items = data.get("events", []) if isinstance(data, dict) else []

    out: List[Dict] = []
    for it in items[:limit]:
        title = (it.get("title") or "").strip()
        url = it.get("url")
        start_iso = it.get("start_date")
        end_iso = it.get("end_date")
        venue = (it.get("venue", {}) or {}).get("address") if isinstance(it.get("venue"), dict) else None
        loc = venue or (it.get("venue", {}) or {}).get("venue") if isinstance(it.get("venue"), dict) else None
        desc = (it.get("excerpt") or it.get("description") or "")[:1000]

        # ensure timezone awareness (Modern Tribe returns local time ISO)
        if start_iso and "Z" not in start_iso and "+" not in start_iso:
            parsed = dateparser.parse(start_iso, settings={"TIMEZONE": tzname, "RETURN_AS_TIMEZONE_AWARE": True})
            if parsed:
                start_iso = parsed.isoformat()
        if end_iso and "Z" not in end_iso and "+" not in end_iso:
            parsed = dateparser.parse(end_iso, settings={"TIMEZONE": tzname, "RETURN_AS_TIMEZONE_AWARE": True})
            if parsed:
                end_iso = parsed.isoformat()

        out.append({
            "title": title or "Untitled",
            "start": start_iso,
            "end": end_iso,
            "location": loc,
            "url": url,
            "description": desc,
            "source": name,
            "source_kind": "Modern Tribe",
            "source_url": base_url,
        })
    return out
