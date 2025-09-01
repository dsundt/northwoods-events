from typing import List, Dict, Any

ALIASES = {
    "the-events-calendar": "modern_tribe",
    "tribe": "modern_tribe",
    "tec": "modern_tribe",
    "growth_zone": "growthzone",
    "gz": "growthzone",
    "sv": "simpleview",
    "simple_view": "simpleview",
}

def normalize_kind(k: str) -> str:
    if not k:
        return k
    k = k.strip().lower()
    return ALIASES.get(k, k)

def resolve_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for s in sources or []:
        if not isinstance(s, dict):
            continue
        name = s.get("name") or s.get("title") or "Unknown"
        url = s.get("url") or s.get("href")
        kind = normalize_kind(s.get("kind"))
        tzname = s.get("tzname")
        if not url or not kind:
            # skip incomplete entries
            continue
        out.append({"name": name, "url": url, "kind": kind, "tzname": tzname})
    return out
