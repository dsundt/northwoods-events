from __future__ import annotations
import re
from datetime import datetime, date
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

__all__ = ["parse_growthzone"]

MONTHS = {
    "jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,"apr":4,"april":4,"may":5,
    "jun":6,"june":6,"jul":7,"july":7,"aug":8,"august":8,"sep":9,"sept":9,"september":9,
    "oct":10,"october":10,"nov":11,"november":11,"dec":12,"december":12
}
DATE_RE = re.compile(rf"(?P<mon>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*)\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?", re.I)

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def _infer_year(mon: int, day: int, year: int | None) -> int:
    if year:
        return year
    today = date.today()
    cand = date(today.year, mon, day)
    if (cand - today).days < -300:
        return today.year + 1
    return today.year

def _parse_one_datetime(text: str) -> str | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    mon = MONTHS.get(m.group("mon").lower())
    if not mon:
        return None
    day = int(m.group("day"))
    year = _infer_year(mon, day, int(m.group("year")) if m.group("year") else None)
    return datetime(year, mon, day).isoformat()

def parse_growthzone(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    anchors = [a for a in soup.find_all("a", href=True) if "/events/details/" in a["href"]]
    for a in anchors:
        url = urljoin(base_url, a["href"])
        title = _text(a) or _text(a.find_parent().find(["h2","h3"]) if a.find_parent() else None)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        container = a.find_parent(["li","article","div"]) or a
        ctx = " ".join([_text(container), _text(container.find_next_sibling())])
        start = _parse_one_datetime(ctx) or _parse_one_datetime(title) or datetime.utcnow().isoformat()
        items.append({"title": title, "start": start, "url": url, "location": ""})

    # Dedup
    seen = set()
    out = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)

    return out[:200]
