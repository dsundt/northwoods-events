# src/parse_simpleview.py
import json
from typing import List
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .utils import norm_event, parse_date, clean_text, save_debug_html


def parse_simpleview(url: str, name: str, tzname: str) -> List[dict]:
    """
    Simpleview (Let's Minocqua, etc.). We normalize the listing view and
    parse via JSON-LD (preferred) with a card fallback.
    """
    # Force a predictable listing view
    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    q.setdefault("view", "list")
    q.setdefault("perpage", "100")
    url = urlunparse(u._replace(query=urlencode(q)))

    html = fetch_html(url, source={"kind": "simpleview", "name": name})
    soup = BeautifulSoup(html, "lxml")

    out: List[dict] = []

    # 1) JSON-LD: can be an array or repeated tags
    for tag in soup.select('script[type="application/ld+json"]'):
        txt = tag.get_text(strip=True)
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue
        blocks = data if isinstance(data, list) else [data]
        for b in blocks:
            at = b.get("@type")
            is_event = (isinstance(at, str) and at == "Event") or (isinstance(at, list) and "Event" in at)
            if not (isinstance(b, dict) and is_event):
                continue
            loc = b.get("location") or {}
            addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
            image = b.get("image")
            image_url = image[0] if isinstance(image, list) else image
            out.append(
                norm_event(
                    source=name,
                    title=b.get("name"),
                    url=b.get("url") or url,
                    start=b.get("startDate"),
                    end=b.get("endDate"),
                    tzname=tzname,
                    location=clean_text(loc.get("name")),
                    city=clean_text(addr.get("addressLocality")),
                    description=clean_text(b.get("description")),
                    image=image_url,
                )
            )

    # 2) Card fallback for common Simpleview grids
    if not out:
        for card in soup.select(".event-card, .event, .lv-event, .listing .event"):
            a = card.select_one("a[href]")
            title = clean_text(a.get_text()) if a else None
            href = a["href"] if a else url
            date_el = card.select_one(".event-card__date, .date, .event-date, time[datetime]")
            date_txt = (
                date_el.get("datetime")
                if date_el and date_el.has_attr("datetime")
                else (date_el.get_text() if date_el else None)
            )
            out.append(
                norm_event(
                    source=name,
                    title=title,
                    url=href,
                    start=parse_date(clean_text(date_txt), tzname),
                    end=None,
                    tzname=tzname,
                    location=None,
                    city=None,
                    description=None,
                    image=None,
                )
            )

    if not out:
        save_debug_html(name, html)

    return out
