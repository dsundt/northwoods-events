# src/resolve_sources.py
from __future__ import annotations

from .parse_modern_tribe import parse_modern_tribe
from .parse_simpleview import parse_simpleview
from .parse_growthzone import parse_growthzone
from .parse_ics import parse_ics

PARSERS = {
    "modern_tribe": parse_modern_tribe,
    "simpleview":   parse_simpleview,
    "growthzone":   parse_growthzone,
    "ics":          parse_ics,
}

def get_parser(kind: str):
    if kind not in PARSERS:
        raise KeyError(f"Unknown parser kind: {kind}")
    return PARSERS[kind]
