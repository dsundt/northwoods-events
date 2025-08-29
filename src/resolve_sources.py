# -*- coding: utf-8 -*-
"""
Map `parser_kind` from sources.yml to callables.
"""

from typing import Callable, Dict

# Core
from .parse_modern_tribe import parse_modern_tribe
from .parse_growthzone import parse_growthzone
from .parse_ai1ec import parse_ai1ec
from .parse_travelwi import parse_travelwi
from .parse_ics import parse_ics
# New
from .parse_simpleview import parse_simpleview
from .parse_st_germain_ajax import parse_st_germain_ajax

PARSERS: Dict[str, Callable] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
    "ai1ec": parse_ai1ec,
    "travelwi": parse_travelwi,
    "ics": parse_ics,
    "simpleview": parse_simpleview,
    "st_germain_ajax": parse_st_germain_ajax,
}

def get_parser(kind: str) -> Callable:
    fn = PARSERS.get(kind)
    if not fn:
        raise ValueError(f"Unknown parser_kind: {kind}")
    return fn
