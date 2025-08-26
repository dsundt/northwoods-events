# src/tec_rest.py
from __future__ import annotations
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, urljoin

def _site_root(url: str) -> str:
    u = urlparse(url)
    return urlunparse((u.scheme, u.netloc, "", "", "", ""))

def _events_api_base(url: str) -> str:
    # The Events Calendar v6 REST base
    return urljoin(_site_root(url), "/wp-json/tribe/events/v1/")

def fetch_events(url: str, months_ahead: int = 12, headers: dict | None = None) -> list[dict]:
    """
    Call TEC REST API and return rows compatible with your pipeline.
    Each row contains: title, url, date_text (''), venue_text, iso_datetime, iso_end
    """
    api = urljoin(_events_api_base(url), "events")
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=30 * months_ahead)

    params = {
        "page": 1,
        "per_page": 100,  # TEC caps ~100
        "start_date": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "end_date": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    rows: list[dict] = []
    session = requests.Session()
    session.headers.update({
        "User-Agent": "northwoods-events/1.0 (+github-actions)",
        "Accept": "application/json",
    })
    if headers:
        session.headers.update(headers)

    while True:
        r = session.get(api, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        events = data.get("events", [])
        for e in events:
            title = (e.get("title") or "").strip()

            # Prefer website/permalink if present
            permalink = (e.get("website") or e.get("url") or "").strip()
            if not permalink:
                permalink = (e.get("url") or "").strip()

            # ISO-ish from TEC; keep as hints for your normalizer/ICS builder
            start = (e.get("start_date") or e.get("start_date_details", {}).get("datetime") or "").strip()
            enddt = (e.get("end_date") or e.get("end_date_details", {}).get("datetime") or "").strip()

            venue = ""
            venue_obj = e.get("venues") or e.get("venue", {})
            if isinstance(venue_obj, list) and venue_obj:
                v = venue_obj[0]
                venue = ", ".join(filter(None, [v.get("venue",""), v.get("city",""), v.get("region",""), v.get("country","")]))
            elif isinstance(venue_obj, dict):
                venue = ", ".join(filter(None, [venue_obj.get("venue",""), venue_obj.get("city",""), venue_obj.get("region",""), venue_obj.get("country","")]))

            rows.append({
                "title": title,
                "url": permalink,
                "date_text": "",         # let your parser use ISO hints below
                "venue_text": venue,
                "iso_datetime": start,
                "iso_end": enddt,
            })

        # Pagination: TEC often supplies next_rest_url but we can safely bump page
        total = data.get("total", 0)
        if params["page"] * params["per_page"] >= total:
            break
        params["page"] += 1
        if params["page"] > 50:   # safety
            break

    return rows
