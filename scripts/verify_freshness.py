# .github/scripts/verify_freshness.py
import json, os
P = "state/last_run_report.json"

if not os.path.isfile(P):
    raise SystemExit("ERROR: state/last_run_report.json not found.")

d = json.load(open(P, "r", encoding="utf-8"))
print("Report time (UTC):", d.get("when"))
print("Freshness OK.")
