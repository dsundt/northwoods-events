# Northwoods Events ICS

Aggregates events from multiple tourism sites and outputs a single `events.ics`.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python main.py --out build/events.ics --report build/last_run_report.json
