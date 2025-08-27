#!/usr/bin/env python3
"""
Utility to test individual event parsers against snapshot HTML/ICS files.

Usage:
  python test_parser.py state/snapshots/vilas_county_(modern_tribe).html modern_tribe
  python test_parser.py state/snapshots/town_of_arbor_vitae_(municipal_calendar).html ai1ec
  python test_parser.py some.ics ics
"""

import sys
import json
from pathlib import Path

# Ensure local src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from parse_ai1ec import parse_ai1ec
from main import parse_modern_tribe_html, parse_growthzone_html, ingest_ics


def usage():
    print(__doc__)
    sys.exit(1)


def main():
    if len(sys.argv) < 3:
        usage()

    file_path = Path(sys.argv[1])
    kind = sys.argv[2].lower()

    if not file_path.exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    text = file_path.read_text(encoding="utf-8", errors="ignore")
    events = []

    if kind in ("modern_tribe", "tribe"):
        events = parse_modern_tribe_html(text)
    elif kind in ("growthzone", "chambermaster"):
        events = parse_growthzone_html(text)
    elif kind in ("ai1ec", "all_in_one", "all-in-one"):
        events = parse_ai1ec(text)
    elif kind == "ics":
        events = ingest_ics(text)
    else:
        print(f"Unknown parser kind: {kind}")
        sys.exit(1)

    print(f"\nParsed {len(events)} events from {file_path} using {kind} parser:\n")

    # Pretty-print all events to log
    for i, ev in enumerate(events, 1):
        title = ev.get("title", "")
        start = ev.get("iso_datetime") or ev.get("date_text", "")
        loc = ev.get("venue_text") or ev.get("location", "")
        url = ev.get("url", "")
        print(f"{i:02d}. {title}")
        print(f"    Start: {start}")
        if loc:
            print(f"    Location: {loc}")
        if url:
            print(f"    URL: {url}")
        print("")

    # Write all events to JSON for artifact upload
    out_file = Path("parsed_events.json")
    out_file.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Wrote all {len(events)} events to {out_file}\n")


if __name__ == "__main__":
    main()
