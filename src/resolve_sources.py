# resolve_sources.py
from __future__ import annotations

from .parse_modern_tribe import parse_modern_tribe
from .parse_simpleview import parse_simpleview
from .parse_growthzone import parse_growthzone
from .parse_micronet_ajax import parse_micronet_ajax
from .parse_ai1ec import parse_ai1ec
from .parse_travelwi import parse_travelwi
from .parse_ics import parse_ics

_ALIASES = {
    "st_germain_ajax": "micronet_ajax",
}

_HANDLERS = {
    "modern_tribe": parse_modern_tribe,
    "simpleview": parse_simpleview,
    "growthzone": parse_growthzone,
    "micronet_ajax": parse_micronet_ajax,
    "ai1ec": parse_ai1ec,
    "travelwi": parse_travelwi,
    "ics": parse_ics,
    "municipal": parse_ai1ec,  # safe default; many municipal WP sites use AI1EC
}


def get_parser(kind: str):
    kind = _ALIASES.get(kind, kind)
    fn = _HANDLERS.get(kind)
    if not fn:
        raise ValueError(f"Unknown source kind: {kind}")
    return fn
