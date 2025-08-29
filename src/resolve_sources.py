from __future__ import annotations
import importlib, inspect
from typing import Callable, Any, Dict

# Map parser_kind -> preferred module name under src/
MOD_FOR_KIND = {
    "modern_tribe": "parse_modern_tribe",
    "growthzone": "parse_growthzone",
    "simpleview": "parse_simpleview",
    "st_germain_ajax": "parse_micronet_ajax",
    "ai1ec": "parse_ai1ec",
    "travelwi": "parse_travelwi",
    "ics": "parse_ics",
    # Many municipal calendars are AI1EC-ish; fall back gracefully
    "municipal": "parse_ai1ec",
}

# Within a module, try these function names (first found wins)
CANDIDATE_FUNCS = [
    "parse_modern_tribe",
    "parse_growthzone",
    "parse_simpleview",
    "parse_micronet_ajax",
    "parse_ai1ec",
    "parse_travelwi",
    "parse_ics",
    "parse",              # generic
    "parse_events",       # generic
]

def _normalize_callable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """
    Wrap `fn` so we can call it as fn(html, base_url, **extras) regardless of its signature.
    We pass common keywords only when accepted, to avoid TypeErrors.
    """
    sig = inspect.signature(fn)
    params = sig.parameters

    def wrapper(html: str, base_url: str, **extras: Any):
        kwargs: Dict[str, Any] = {}
        # common aliases for the HTML
        for html_key in ("html", "text", "content", "page_html"):
            if html_key in params:
                kwargs[html_key] = html
                break
        # base URL
        for url_key in ("base_url", "url", "source_url"):
            if url_key in params:
                kwargs[url_key] = base_url
                break
        # let extras through if accepted
        for k, v in extras.items():
            if k in params:
                kwargs[k] = v
        # positional fallback (html, base_url)
        try:
            return fn(**kwargs)
        except TypeError:
            try:
                return fn(html, base_url)
            except TypeError:
                try:
                    return fn(html)
                except TypeError:
                    return fn()
    return wrapper

def get_parser(parser_kind: str) -> Callable[..., Any] | None:
    kind = (parser_kind or "").lower()
    mod_name = MOD_FOR_KIND.get(kind)
    if not mod_name:
        return None
    try:
        mod = importlib.import_module(f"src.{mod_name}")
    except Exception:
        # Try under src.parsers as a fallback
        try:
            mod = importlib.import_module(f"src.parsers.{mod_name}")
        except Exception:
            return None

    for fname in CANDIDATE_FUNCS:
        fn = getattr(mod, fname, None)
        if callable(fn):
            return _normalize_callable(fn)
    return None
