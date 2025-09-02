# src/resolve_sources.py
"""
Resolve a source 'kind' to a parser function, and return a wrapper that
normalizes call arguments. This ensures parsers always receive:
    url=..., add_event=..., source=..., tzname=...
even if the caller uses old positional ordering like:
    parser(add_event, url, name, tzname)

This file is intentionally tiny and traceable: it introduces no new logic,
only argument normalization in one place.
"""

from __future__ import annotations

# Import available parsers. If any is optional in your repo, keep the import
# but feel free to remove its key from PARSERS below.
from .parse_modern_tribe import parse_modern_tribe
from .parse_growthzone import parse_growthzone
from .parse_simpleview import parse_simpleview
from .parse_ics import parse_ics


# Map 'kind' -> parser function
PARSERS = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
    "simpleview": parse_simpleview,
    "ics": parse_ics,
}


def get_parser(kind: str):
    """
    Returns a callable that accepts either:
      - legacy positional usage: (add_event, url, name, tzname?)
      - or keyword usage: url=..., add_event=..., source=..., tzname=...

    and forwards to the real parser with keyword arguments:
      parser(url=url, add_event=add_event, source=source, name=source, tzname=tzname, **extras)
    """
    kind = (kind or "").strip().lower()
    parser = PARSERS.get(kind)
    if not parser:
        raise ValueError(f"Unknown source kind: {kind!r}")

    def _normalized(*args, **kwargs):
        # If already called with keywords, pass through (but also mirror 'source' to 'name' if needed)
        if "url" in kwargs or "add_event" in kwargs:
            url = kwargs.get("url")
            add_event = kwargs.get("add_event")
            source = kwargs.get("source") or kwargs.get("name")

            # Build a clean kw dict for the real parser
            extras = {k: v for k, v in kwargs.items() if k not in {"url", "add_event", "source", "name", "tzname"}}
            clean = dict(
                url=url,
                add_event=add_event,
                source=source,
                name=source,      # some parsers expect `name`; others expect `source`
                tzname=kwargs.get("tzname"),
                **extras,
            )
            return parser(**clean)

        # Legacy positional call path: (add_event, url, name, tzname?)
        if not args or len(args) < 2:
            raise TypeError(
                "Parser called with insufficient positional arguments. "
                "Expected at least (add_event, url, [name], [tzname])."
            )

        add_event = args[0]
        url = args[1]
        source = args[2] if len(args) > 2 else kwargs.get("source") or kwargs.get("name")
        tzname = args[3] if len(args) > 3 else kwargs.get("tzname")

        # Forward with explicit keywords so the real parser never misreads positions
        extras = {k: v for k, v in kwargs.items() if k not in {"url", "add_event", "source", "name", "tzname"}}
        return parser(url=url, add_event=add_event, source=source, name=source, tzname=tzname, **extras)

    return _normalized
