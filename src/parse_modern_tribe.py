# -*- coding: utf-8 -*-
"""
Compatibility wrapper for Modern Tribe parser.

This module supports BOTH legacy and new call styles:

Legacy (used by older `main.py`):
    parse_modern_tribe(source: Mapping, add_event: Callable) -> int

New/streaming style (generator):
    parse_modern_tribe(source_name: str, url: str, tzname: str | None = None) -> Iterator[dict]

Internally this delegates to `src.scrapers.modern_tribe.scrape`, so the single source
of scraping logic lives in one place.
"""
from __future__ import annotations
from typing import Callable, Iterator, Mapping, Optional, Any, Iterable
from .scrapers.modern_tribe import scrape as _scrape


def _emit(events: Iterable[dict], add_event: Callable[[dict], Any]) -> int:
    n = 0
    for ev in events:
        add_event(ev)
        n += 1
    return n


def parse_modern_tribe(*args, **kwargs):
    # Legacy style: parse_modern_tribe(source, add_event)
    if args and isinstance(args[0], Mapping):
        source: Mapping[str, Any] = args[0]
        add_event: Optional[Callable[[dict], Any]] = kwargs.get("add_event")
        if add_event is None and len(args) >= 2 and callable(args[1]):
            add_event = args[1]
        if add_event is None:
            raise TypeError("parse_modern_tribe(source, add_event) requires an add_event callback")
        name = source.get("name") or source.get("source_name") or "Modern Tribe"
        url = source.get("url")
        tzname = source.get("tzname")
        if not url:
            raise ValueError("source['url'] is required")
        # Delegate to scraper (positional args to avoid name mismatches)
        return _emit(_scrape(url, name, tzname), add_event)

    # New style: parse_modern_tribe(source_name, url, tzname=None) -> Iterator[dict]
    # Accept keywords or positionals.
    if args:
        source_name = args[0]
        url = args[1]
        tzname = args[2] if len(args) > 2 else None
    else:
        source_name = kwargs["source_name"]
        url = kwargs["url"]
        tzname = kwargs.get("tzname")
    return _scrape(url, source_name, tzname)
