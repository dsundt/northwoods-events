"""
Central registry for all parsers.

Each parser must expose a function with signature:
    parse_xxx(html: str, base_url: str) -> list[Event]

We register those functions by a simple string key (the `kind` in sources.yml).
"""

from typing import Callable, Dict

# Import the concrete parser modules so their functions are available.
# Keep imports local to avoid heavy import cost if you later add many parsers.
from .modern_tribe import parse_modern_tribe   # noqa: F401
from .simpleview import parse_simpleview       # noqa: F401
from .growthzone import parse_growthzone       # noqa: F401
# If you add more parser modules, import them here and register below.

# Registry: maps kind -> callable(html, base_url) -> list[Event]
_REGISTRY: Dict[str, Callable] = {
    "modern_tribe": parse_modern_tribe,
    "simpleview": parse_simpleview,
    "growthzone": parse_growthzone,
    # Back-compat aliases (in case your sources.yml uses older names)
    "moderntribe": parse_modern_tribe,
    "tec": parse_modern_tribe,
    "sv": parse_simpleview,
}

def get_parser(kind: str) -> Callable:
    """
    Return a parser function for the given kind.
    Raise ValueError with a helpful message if not found.
    """
    k = (kind or "").strip().lower()
    if k in _REGISTRY:
        return _REGISTRY[k]
    # Helpful hint in the error message
    raise ValueError(f"No parser available for kind='{kind}'. "
                     f"Known: {', '.join(sorted(_REGISTRY.keys()))}")
