# .github/scripts/extract_sources.py
import sys, os, yaml

SRC_FILE_CANDIDATES = ["sources.yml", "sources.yaml"]
OUT_PATH = ".tmp.sources.yaml"

src_file = None
for cand in SRC_FILE_CANDIDATES:
    if os.path.isfile(cand):
        src_file = cand
        break

if not src_file:
    print("ERROR: sources.yml not found at repo root.", file=sys.stderr)
    with open(OUT_PATH, "w", encoding="utf-8") as w:
        yaml.safe_dump({"sources": []}, w, sort_keys=False)
    sys.exit(1)

with open(src_file, "r", encoding="utf-8") as f:
    raw = yaml.safe_load(f) or {}

sources = raw.get("sources", [])
if not isinstance(sources, list):
    print("ERROR: 'sources' must be a list in sources.yml.", file=sys.stderr)
    sys.exit(1)

clean = []
for s in sources:
    if not isinstance(s, dict):
        continue
    name = s.get("name")
    kind = s.get("kind")
    url = s.get("url")
    if not name or not kind or not url:
        continue
    clean.append({
        "name": name,
        "kind": kind,
        "url": url,
        "tzname": s.get("tzname")
    })

if not clean:
    print("ERROR: no valid sources found in sources.yml.", file=sys.stderr)
    sys.exit(1)

with open(OUT_PATH, "w", encoding="utf-8") as w:
    yaml.safe_dump({"sources": clean}, w, sort_keys=False)

print(f"Wrote {len(clean)} sources to {OUT_PATH}")
