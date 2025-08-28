from __future__ import annotations
import re
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.dates import parse_datetime_range

__all__ = ["parse_municipal"]

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Handle common municipal calendars (WordPress, FullCalendar, SimpleList).
    Skip 'Untitled' placeholders and external promo links.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # FullCalendar style
    # <a class="fc-daygrid-event" href="..."><div class="fc-event-title">...</div></a>
    anchors = soup.select("a.fc-daygrid-event, a.fc-event, .calendar a[href]")
    if not anchors:
        anchors = soup.find_all("a", href=True)

    seen = set()
    for a in anchors:
        href = a.get("href", "")
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)

        container = a.find_parent(["div", "li", "td", "tr"]) or a
        title = _text(container.find(class_=re.compile(r"(event-title|fc-event-title|title)", re.I))) or _text(a)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or title.lower().startswith("untitled"):
            continue

        # Find YYYY-MM-DD or Month Day near the anchor
        ctx = " ".join([_text(container), _text(container.find_previous_sibling()), _text(container.find_next_sibling())])
        m = re.search(r"\b\d{4}-\d{2}-\d{2}\b", ctx)
        start = None
        if m:
            # normalize to ISO midnight local
            start = f"{m.group(0)}T00:00:00"
        else:
            m2 = re.search(r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?", ctx, flags=re.I)
            if m2:
                try:
                    start = parse_datetime_range(m2.group(0))
                except Exception:
                    start = None

        if not start:
            continue

        # Avoid obvious external ad/promo rows
        if "minocqua.org" in url and "calendar" not in base_url:
            # On Arbor Vitae snapshot this was a static promo link; skip
            continue

        items.append({"title": title, "start": start, "url": url, "location": ""})

    return items
