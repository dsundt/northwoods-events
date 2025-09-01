# .github/scripts/extract_sources.py
import sys, os, yaml

SRC_FILE_CANDIDATES = ["sources.yml", "sources.yaml"]
OUT_PATH = ".tmp.sources.yaml"

def main():
    src_file = next((c for c in SRC_FILE_CANDIDATES if os.path.isfile(c)), None)
    if not src_file:
        print("ERROR: sources.yml not found at repo root.", file=sys.stderr)
        with open(OUT_PATH, "w", encoding="utf-8") as w:
            yaml.safe_dump({"sources": []}, w, sort_keys=False)
        sys.exit(1)

    raw = yaml.safe_load(open(src_file, "r", encoding="utf-8")) or {}
    sources = raw.get("sources", [])
    clean = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        if s.get("enabled") is False:
            continue
        name = s.get("name"); kind = s.get("kind"); url = s.get("url"); tz = s.get("tzname")
        if not name or not kind or not url:
            continue
        clean.append({"name": name, "kind": kind, "url": url, "tzname": tz})

    if not clean:
        print("ERROR: no valid sources found in sources.yml.", file=sys.stderr)
        sys.exit(1)

    yaml.safe_dump({"sources": clean}, open(OUT_PATH, "w", encoding="utf-8"), sort_keys=False)
    print(f"Wrote {len(clean)} sources to {OUT_PATH}")

if __name__ == "__main__":
    main()
