# src/resolve_sources.py
"""
Resolve a source 'kind' to the appropriate parser function that already exists
in this repo. No new parsing logic — just a simple router.

Supported kinds (and aliases):
  - modern_tribe, tribe, the_events_calendar
  - growthzone
  - simpleview, minocqua, letsminocqua
  - ai1ec, allinoneevents
  - ics, icalendar
"""

from typing import Callable, Optional

# Import the existing parser functions from your repository
from .parse_modern_tribe import parse_modern_tribe
from .parse_growthzone import parse_growthzone
from .parse_simpleview import parse_simpleview
from .parse_ai1ec import parse_ai1ec
from .parse_ics import parse_ics


def get_parser(kind: str) -> Optional[Callable]:
    """Return the parser callable for a given kind string, or None if unknown."""
    if not kind:
        return None

    k = (kind or "").strip().lower()

    # Normalize common aliases → canonical keys
    alias = {
        # Modern Tribe / The Events Calendar
        "tribe": "modern_tribe",
        "the_events_calendar": "modern_tribe",
        "the-events-calendar": "modern_tribe",

        # GrowthZone
        "gz": "growthzone",

        # Simpleview / Let's Minocqua
        "minocqua": "simpleview",
        "letsminocqua": "simpleview",
        "let’s minocqua": "simpleview",
        "lets minocqua": "simpleview",

        # All-in-One Event Calendar (AI1EC)
        "allinoneevents": "ai1ec",
        "all-in-one-event-calendar": "ai1ec",

        # ICS / iCalendar
        "icalendar": "ics",
        "ical": "ics",
    }
    k = alias.get(k, k)

    handlers = {
        "modern_tribe": parse_modern_tribe,
        "growthzone": parse_growthzone,
        "simpleview": parse_simpleview,
        "ai1ec": parse_ai1ec,
        "ics": parse_ics,
    }
    return handlers.get(k)
