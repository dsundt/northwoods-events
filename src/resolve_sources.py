# resolve_sources.py
from __future__ import annotations

from .parse_modern_tribe import parse_modern_tribe
from .parse_simpleview import parse_simpleview
from .parse_growthzone import parse_growthzone
from .parse_micronet_ajax import parse_micronet_ajax
from .parse_ai1ec import parse_ai1ec
from .parse_travelwi import parse_travelwi
from .parse_ics import parse_ics
from .parse_squarespace_calendar import parse_squarespace_calendar  # <-- NEW


_ALIASES = {
    "st_germain_ajax": "micronet_ajax",
    "squarespace_calendar": "squarespace",  # allow either label
}

_HANDLERS = {
    "modern_tribe": parse_modern_tribe,
    "simpleview": parse_simpleview,
    "growthzone": parse_growthzone,
    "micronet_ajax": parse_micronet_ajax,
    "ai1ec": parse_ai1ec,
    "travelwi": parse_travelwi,
    "ics": parse_ics,
    "municipal": parse_ai1ec,           # unchanged fallback
    "squarespace": parse_squarespace_calendar,  # <-- NEW
}


def get_parser(kind: str):
    kind = _ALIASES.get(kind, kind)
    fn = _HANDLERS.get(kind)
    if not fn:
        raise ValueError(f"Unknown source kind: {kind}")
    return fn
