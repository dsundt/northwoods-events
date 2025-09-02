# -*- coding: utf-8 -*-
"""
Compatibility wrapper for ICS parser.

Supports both legacy and new call styles by delegating to `src.scrapers.icsfeed.scrape`.
"""
from __future__ import annotations
from typing import Callable, Iterator, Mapping, Optional, Any, Iterable
from .scrapers.icsfeed import scrape as _scrape


def _emit(events: Iterable[dict], add_event: Callable[[dict], Any]) -> int:
    n = 0
    for ev in events:
        add_event(ev)
        n += 1
    return n


def parse_ics(*args, **kwargs):
    # Legacy style: parse_ics(source, add_event)
    if args and isinstance(args[0], Mapping):
        source: Mapping[str, Any] = args[0]
        add_event: Optional[Callable[[dict], Any]] = kwargs.get("add_event")
        if add_event is None and len(args) >= 2 and callable(args[1]):
            add_event = args[1]
        if add_event is None:
            raise TypeError("parse_ics(source, add_event) requires an add_event callback")
        name = source.get("name") or source.get("source_name") or "ICS"
        url = source.get("url")
        tzname = source.get("tzname")
        if not url:
            raise ValueError("source['url'] is required")
        # Delegate to scraper (positional args to avoid name mismatches)
        return _emit(_scrape(url, name, tzname), add_event)

    # New style: parse_ics(source_name, url, tzname=None) -> Iterator[dict]
    if args:
        source_name = args[0]
        url = args[1]
        tzname = args[2] if len(args) > 2 else None
    else:
        source_name = kwargs["source_name"]
        url = kwargs["url"]
        tzname = kwargs.get("tzname")
    return _scrape(url, source_name, tzname)
