from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# This parser first tries to parse the visible HTML (robust fallback),
# and if an AJAX payload is embedded, it will use that. In your CI runner,
# we only have the HTML snapshot, so the HTML path is key.

__all__ = ["parse_st_germain_ajax"]


def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""


def _parse_html_cards(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Look for the typical WP event listing area
    cards = soup.select("article, .event, .tribe-events-calendar-list__event, .et_pb_post")
    if not cards:
        cards = soup.select("li, .card, .entry-summary")

    for c in cards:
        a = c.find("a", href=True)
        if not a:
            continue
        title = _text(c.find(["h3", "h2"])) or _text(a)
        title = re.sub(r"\s+", " ", (title or "")).strip()
        if not title:
            continue

        # Find a date string in the card
        dt = ""
        for sel in ["time", ".tribe-event-date-start", ".tribe-event-date", ".date", ".entry-date"]:
            el = c.select_one(sel)
            if el:
                if el.has_attr("datetime"):
                    dt = el["datetime"]
                else:
                    dt = _text(el)
                break

        if not dt:
            # try generic text in the card (rare)
            dt = _text(c)

        # Very light month/day detector to avoid false positives
        if not re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b", dt, re.I):
            continue

        url = urljoin(base_url, a["href"])
        location = ""
        loc_el = c.find(class_=re.compile("location|venue", re.I))
        if loc_el:
            location = _text(loc_el)

        # Do not try to normalize date here; let upstream utils handle it when ingesting detail page.
        items.append({"title": title, "start": dt.strip(), "url": url, "location": location})

    return items


def parse_st_germain_ajax(html: str, base_url: str) -> List[Dict[str, Any]]:
    # 1) Robust HTML fallback
    items = _parse_html_cards(html, base_url)
    if items:
        return items

    # 2) If the page embeds a JSON of posts (rare), parse it
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")
    for s in scripts:
        txt = s.string or s.text or ""
        if "wp-json" in txt or "tribe_events" in txt:
            try:
                data = json.loads(txt)
                out: List[Dict[str, Any]] = []
                for post in data.get("posts", []):
                    title = post.get("title") or ""
                    url = urljoin(base_url, post.get("link") or "")
                    date_txt = post.get("date") or post.get("start_date") or ""
                    if title and url and date_txt:
                        out.append({"title": title, "start": date_txt, "url": url, "location": ""})
                if out:
                    return out
            except Exception:
                continue

    # 3) Nothing found
    return []
