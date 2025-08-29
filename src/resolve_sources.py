# src/resolve_sources.py
from __future__ import annotations

from .parse_modern_tribe import parse_modern_tribe
from .parse_simpleview import parse_simpleview
from .parse_growthzone import parse_growthzone
from .parse_ai1ec import parse_ai1ec
from .parse_ics import parse_ics

_ALIASES = {
    # Legacy aliases that should resolve cleanly
    "st_germain_ajax": "modern_tribe",
    "micronet_ajax": "growthzone",  # Micronet/ChamberMaster typically = GrowthZone
    "municipal": "ai1ec",
    "squarespace_calendar": "ai1ec",
}

_HANDLERS = {
    "modern_tribe": parse_modern_tribe,
    "simpleview": parse_simpleview,
    "growthzone": parse_growthzone,
    "ai1ec": parse_ai1ec,
    "ics": parse_ics,
}

def get_parser(kind: str):
    k = (kind or "").strip().lower()
    k = _ALIASES.get(k, k)
    fn = _HANDLERS.get(k)
    if not fn:
        raise ValueError(f"Unknown source kind: {kind}")
    return fn
