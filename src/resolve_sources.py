# src/resolve_sources.py
from __future__ import annotations
from typing import Callable, Dict, Any, List

# Import parsers with relative imports, but keep a fallback for script-mode
try:
    from .parse_modern_tribe import parse_modern_tribe
    from .parse_growthzone import parse_growthzone
    from .parse_ics import parse_ics
    from .parse_simpleview import parse_simpleview
except ImportError:
    from parse_modern_tribe import parse_modern_tribe
    from parse_growthzone import parse_growthzone
    from parse_ics import parse_ics
    from parse_simpleview import parse_simpleview


Parser = Callable[[Dict[str, Any]], List[Dict[str, Any]]]

REGISTRY: Dict[str, Parser] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone":   parse_growthzone,
    "ics":          parse_ics,
    "simpleview":   parse_simpleview,  # Let’s Minocqua
}


def get_parser(kind: str | None) -> Parser | None:
    if not kind:
        return None
    return REGISTRY.get(kind.strip().lower())


# Back-compat shim for older code that did:
#   from resolve_sources import resolve_sources
#   parser = resolve_sources(kind)
def resolve_sources(kind: str | None) -> Parser | None:  # noqa: N802 (keep legacy name)
    return get_parser(kind)
