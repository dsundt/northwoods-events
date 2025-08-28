from __future__ import annotations

import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

# ---- Parsers ----
from parsers.modern_tribe import parse_modern_tribe
from parsers.growthzone import parse_growthzone

# Optional parsers (present in your repo, but we won't hard-require them)
try:
    from parsers.simpleview import parse_simpleview  # type: ignore
except Exception:  # pragma: no cover
    parse_simpleview = None  # type: ignore

try:
    from parsers.municipal import parse_municipal  # type: ignore
except Exception:  # pragma: no cover
    parse_municipal = None  # type: ignore


# ---- Config dataclasses ----

@dataclass
class Source:
    name: str
    url: str
    kind: str

@dataclass
class Defaults:
    tzname: str = "America/Chicago"
    default_duration_minutes: int = 120

@dataclass
class RunRow:
    name: str
    url: str
    fetched: int = 0
    parsed: int = 0
    added: int = 0
    samples: List[Dict[str, Any]] = None  # type: ignore
    http_status: Optional[int] = None
    snapshot: Optional[str] = None
    parser_kind: Optional[str] = None
    notes: Dict[str, Any] = None  # type: ignore
    error: Optional[str] = None
    traceback: Optional[str] = None


# ---- YAML loader ----

def load_sources_from_yaml(path: str) -> tuple[Defaults, List[Source]]:
    with open(path, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f) or {}
    defaults = Defaults(**(y.get("defaults") or {}))
    srcs = [Source(**s) for s in (y.get("sources") or [])]
    return defaults, srcs


# ---- Snapshot helpers ----

def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[\s/]+", "_", s)
    s = re.sub(r"[^a-z0-9_()+-]+", "", s)
    return s

def _snap_path(name: str, kind: str) -> str:
    os.makedirs("state/snapshots", exist_ok=True)
    return os.path.join("state", "snapshots", f"{_slug(name)}.html")

def _write_snapshot(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---- Fetchers ----

def _http_get(url: str) -> tuple[str, int]:
    r = requests.get(url, timeout=30, headers={"User-Agent": "northwoods-events/1.0"})
    return r.text, r.status_code


def st_germain_ajax_fetch(list_url: str) -> dict:
    """
    Special fetch for St. Germain (Micronet/WordPress AJAX).
    If AJAX fails, we fall back to the regular list page HTML.
    Returns: {"html": "<...>", "notes": {...}}
    """
    notes: Dict[str, Any] = {"attempt": "ajax"}

    try:
        # Try to discover the AJAX endpoint from the page itself
        html, status = _http_get(list_url)
        notes["list_status"] = status
        soup = BeautifulSoup(html, "html.parser")

        ajaxurl = None
        for s in soup.find_all("script"):
            if s.string and "admin-ajax.php" in s.string:
                m = re.search(r"(https?:\/\/[^\"']+admin-ajax\.php)", s.string)
                if m:
                    ajaxurl = m.group(1)
                    break
        if not ajaxurl:
            # default guess for WP sites
            parsed = urlparse(list_url)
            ajaxurl = f"{parsed.scheme}://{parsed.netloc}/wp-admin/admin-ajax.php"
        notes["ajaxurl"] = ajaxurl

        # Try common action/params used by Micronet event shortcodes
        payloads = [
            {"action": "load_events", "page": 1},
            {"action": "tribe_event_list", "paged": 1},
            {"action": "events", "paged": 1},
        ]
        gathered: List[str] = []
        for p in payloads:
            try:
                r = requests.post(ajaxurl, data=p, timeout=30)
                if r.status_code == 200 and ("event" in r.text.lower() or "<article" in r.text.lower()):
                    gathered.append(r.text)
                    break
            except Exception:
                continue

        if gathered:
            html_combined = "\n".join(gathered)
            notes["pages"] = len(gathered)
            return {"html": html_combined, "notes": notes}

        # Fallback to list page HTML
        notes["pages"] = 1
        notes["fallback"] = True
        return {"html": html, "notes": notes}
    except Exception as e:
        # Final fallback: GET the list page
        notes["exception"] = str(e)
        html, _ = _http_get(list_url)
        notes["fallback"] = True
        return {"html": html, "notes": notes}


# ---- Parser registry ----

PARSERS: Dict[str, Callable[[str, str], List[Dict[str, Any]]]] = {
    "modern_tribe": parse_modern_tribe,
    "growthzone": parse_growthzone,
}

if parse_simpleview:
    PARSERS["simpleview"] = parse_simpleview  # type: ignore
if parse_municipal:
    PARSERS["municipal"] = parse_municipal  # type: ignore

# st_germain_ajax is handled here (fetch differs), but we still parse via modern_tribe after fetch.
PARSERS["st_germain_ajax"] = parse_modern_tribe


# ---- Pipeline ----

def run_pipeline(defaults: Defaults, sources: List[Source]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "when": datetime.now().astimezone().isoformat(),
        "timezone": defaults.tzname,
        "sources": [],
        "meta": {"status": "ok", "sources_file": "sources.yml"},
    }

    for s in sources:
        row = RunRow(
            name=s.name,
            url=s.url,
            samples=[],
            notes={},
            parser_kind=s.kind,
        )
        try:
            if s.kind == "st_germain_ajax":
                fetch = st_germain_ajax_fetch(s.url)
                html = fetch["html"]
                row.notes.update(fetch.get("notes", {}))
                status = row.notes.get("list_status") or 200
                row.http_status = int(status)
            else:
                html, status = _http_get(s.url)
                row.http_status = status

            row.fetched = 1

            # Save snapshot
            snap = _snap_path(f"{s.name} ({s.kind})", s.kind)
            _write_snapshot(snap, html)
            row.snapshot = snap

            # Parse
            parser = PARSERS.get(s.kind)
            if not parser:
                raise RuntimeError(f"No parser for kind={s.kind}")

            items = parser(html, base_url=s.url) or []
            row.parsed = len(items)
            row.added = len(items)
            row.samples = items[:3]

        except Exception as e:
            row.error = repr(e)
            row.traceback = "".join(traceback.format_exception(*sys.exc_info()))

        out["sources"].append(asdict(row))

    return out


# ---- Reporting ----

def _write_reports(report: Dict[str, Any]) -> List[str]:
    pretty = json.dumps(report, indent=2, ensure_ascii=False)
    os.makedirs("state", exist_ok=True)
    with open("last_run_report.json", "w", encoding="utf-8") as f:
        f.write(pretty)
    with open(os.path.join("state", "last_run_report.json"), "w", encoding="utf-8") as f:
        f.write(pretty)
    return ["last_run_report.json", os.path.join("state", "last_run_report.json")]


# ---- Main ----

def main() -> None:
    # Allow running from repo root or from src/
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here))
    yaml_path = os.path.join(root, "sources.yml")
    if not os.path.exists(yaml_path):
        yaml_path = os.path.join(os.path.dirname(root), "sources.yml")

    defaults, srcs = load_sources_from_yaml(yaml_path)
    report = run_pipeline(defaults, srcs)
    paths = _write_reports(report)
    print("last_run_report.json written to:")
    for p in paths:
        print(" -", p)
    print(f"Summary: parsed={sum(s.get('parsed', 0) for s in report['sources'])}, "
          f"added={sum(s.get('added', 0) for s in report['sources'])}")


if __name__ == "__main__":
    main()
