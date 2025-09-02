# src/utils/__init__.py
"""
Facade for utils so legacy imports like:
  from .utils import norm_event, parse_date, clean_text, save_debug_html
keep working no matter how internals are organized.
"""

from __future__ import annotations
from pathlib import Path

# Pull in canonical implementations
# - clean_text / normalize_event / parse_dt live in src/normalize.py
# - parse_date may live in src/utils/dates.py; fall back to parse_dt if needed
from ..normalize import clean_text, normalize_event as _normalize_event, parse_dt as _parse_dt

try:
    # Prefer your dedicated date parser if present
    from .dates import parse_date as _parse_date  # type: ignore
except Exception:  # pragma: no cover
    _parse_date = None  # fallback to _parse_dt below


def parse_date(s: str, tz=None):
    """Compat shim: prefer utils.dates.parse_date, else fall back to normalize.parse_dt."""
    if _parse_date is not None:
        return _parse_date(s, tz=tz)
    return _parse_dt(s, tz=tz)


def norm_event(e: dict) -> dict:
    """Compat alias for normalize.normalize_event."""
    return _normalize_event(e)


def save_debug_html(html: str, filename: str = "debug", subdir: str = "debug") -> str:
    """
    Write HTML into state/<subdir>/<filename>.html for troubleshooting in Actions artifacts.
    Returns the path written.
    """
    out_dir = Path("state") / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (filename if filename.endswith(".html") else f"{filename}.html")
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


# Re-export common helpers for convenience
parse_dt = _parse_dt  # sometimes imported directly

__all__ = ["clean_text", "parse_date", "parse_dt", "norm_event", "save_debug_html"]
