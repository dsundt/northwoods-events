from __future__ import annotations
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""

def parse_municipal(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []
    main = soup.find("main") or soup
    for a in main.find_all("a", href=True):
        href = a["href"]
        if not href or href.startswith("#"):
            continue
        title = _text(a).strip()
        if not title:
            continue
        # Pull a nearby date if present
        container = a.find_parent(["li", "article", "div"]) or a
        dt = ""
        for cls in ("date","time","event-date","event-time"):
            el = container.find(class_=cls)
            if el:
                dt = _text(el)
                break
        items.append({
            "title": title,
            "start": dt,
            "url": urljoin(base_url, href),
            "location": "",
        })
    # Dedup by URL
    seen = set()
    out = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
    return out[:200]
