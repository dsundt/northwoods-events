#!/usr/bin/env python3
"""
Utility to test individual event parsers against snapshot HTML/ICS files.

Usage:
  python -m src.test_parser state/snapshots/vilas_county_(modern_tribe).html modern_tribe
  python -m src.test_parser state/snapshots/town_of_arbor_vitae_(municipal_calendar).html ai1ec
  python -m src.test_parser some.ics ics
"""

import sys
import json
from pathlib import Path

# Make the package (src/) importable when running from repo root
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parse_ai1ec import parse_ai1ec
from parse_modern_tribe import parse_modern_tribe
from parse_growthzone import parse_growthzone
from parse_ics import parse_ics

def main():
    if len(sys.argv) < 3:
        print("Usage: python -m src.test_parser <snapshot.html|.ics> <kind>")
        sys.exit(2)

    path = Path(sys.argv[1])
    kind = sys.argv[2].strip().lower()

    text = path.read_text(encoding="utf-8")
    events = []

    def add_event(e): events.append(e)

    if kind == "modern_tribe":
        import parse_modern_tribe as mt
        real_fetch = mt.fetch_html
        try:
            mt.fetch_html = lambda *_a, **_k: text
            parse_modern_tribe({"url": "file://"+str(path), "tzname": "America/Chicago"}, add_event)
        finally:
            mt.fetch_html = real_fetch
    elif kind == "growthzone":
        import parse_growthzone as gz
        real_fetch = getattr(gz, "fetch_html", None)
        try:
            if real_fetch:
                gz.fetch_html = lambda *_a, **_k: text
            parse_growthzone({"url": "file://"+str(path), "tzname": "America/Chicago"}, add_event)
        finally:
            if real_fetch:
                gz.fetch_html = real_fetch
    elif kind == "ai1ec":
        import parse_ai1ec as a
        real_fetch = a.fetch_html
        try:
            a.fetch_html = lambda *_a, **_k: text
            parse_ai1ec({"url": "file://"+str(path), "tzname": "America/Chicago"}, add_event)
        finally:
            a.fetch_html = real_fetch
    elif kind == "ics":
        parse_ics({"url": "file://"+str(path), "tzname": "America/Chicago"}, add_event)
    else:
        print(f"Unknown kind: {kind}")
        sys.exit(2)

    Path("parsed_events.json").write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Parsed {len(events)} events; wrote parsed_events.json")

if __name__ == "__main__":
    main()
