from __future__ import annotations
import json
import re
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from utils.dates import combine_date_and_time, parse_datetime_range

__all__ = ["parse_st_germain_ajax"]

# This parser:
# 1) Reads the localized settings object to get ajaxurl + nonce.
# 2) Calls admin-ajax with action=mbi_filter_events and start_date=today.
# 3) Handles JSON with {success, data:{listings:[...]}} or {success, data:{html:"..."}}

LOC_OBJ_RE = re.compile(
    r"(micronet_api_(?:intergration|integration)_for_wordpress_ajax)\s*=\s*(\{.*?\});",
    re.S | re.I
)

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _load_localized_config(html: str) -> Optional[Dict[str, Any]]:
    m = LOC_OBJ_RE.search(html or "")
    if not m:
        return None
    # m.group(1) is the variable name, m.group(2) is the JSON
    try:
        return json.loads(m.group(2))
    except Exception:
        return None

def _post_fetch(config: Dict[str, Any], base_url: str, page: int = 1) -> Optional[Dict[str, Any]]:
    ajaxurl = config.get("ajaxurl") or urljoin(base_url, "/wp-admin/admin-ajax.php")
    nonce = config.get("nonce", "")
    data = {
        "action": "mbi_filter_events",
        "security": nonce,
        "start_date": date.today().isoformat(),
        "page": page,
    }
    headers = {"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest"}
    try:
        resp = requests.post(ajaxurl, data=data, headers=headers, timeout=20)
        if "application/json" in (resp.headers.get("Content-Type") or ""):
            return resp.json()
        # Some installs echo JSON as text/plain
        try:
            return resp.json()
        except Exception:
            return None
    except Exception:
        return None

def _parse_listings_html(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, Any]] = []
    # A listing is usually a card with an <a href="/events/..."> and visible date text.
    for card in soup.select("article, .card, li, .listing, .event, .mbi-listing"):
        a = card.find("a", href=True)
        if not a or "/events/" not in a["href"]:
            continue
        title = _text(card.find(["h3", "h2"])) or a.get_text(strip=True)
        # Date/time text is often on the card; combine if possible
        time_text = _text(card)
        start_iso = None
        # prefer <time datetime>
        t = card.find("time", attrs={"datetime": True})
        if t:
            start_iso = combine_date_and_time(t.get("datetime", ""), t.get_text(" ", strip=True))
        if not start_iso:
            try:
                start_iso = parse_datetime_range(time_text)
            except Exception:
                start_iso = None
        out.append({
            "title": title,
            "start": start_iso or "",
            "url": urljoin(base_url, a["href"]),
            "location": "",
        })
    return out

def _parse_listings_objects(objs: List[Dict[str, Any]], base_url: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for o in objs or []:
        title = o.get("name") or o.get("title") or ""
        link = o.get("link") or o.get("url") or ""
        date_str = o.get("event_date") or o.get("date") or ""
        time_str = o.get("event_time") or o.get("time") or ""
        start_iso = None
        if date_str:
            start_iso = combine_date_and_time(date_str, time_str)
        if not start_iso:
            try:
                start_iso = parse_datetime_range(f"{date_str} {time_str}".strip())
            except Exception:
                start_iso = ""
        out.append({
            "title": title.strip(),
            "start": start_iso,
            "url": urljoin(base_url, link),
            "location": (o.get("location") or "").strip(),
        })
    return out

def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict[str, Any]]:
    config = _load_localized_config(html)
    if not config:
        return []  # nothing we can do without ajaxurl/nonce

    res = _post_fetch(config, base_url, page=1)
    if not res or not isinstance(res, dict) or not res.get("success"):
        return []

    data = res.get("data") or {}
    if isinstance(data, dict):
        # objects array?
        if isinstance(data.get("listings"), list):
            return _parse_listings_objects(data["listings"], base_url)
        # raw HTML?
        for key in ("html", "listings_html", "results_html"):
            if isinstance(data.get(key), str):
                return _parse_listings_html(data[key], base_url)

    return []
