# File: src/resolve_sources.py
from __future__ import annotations
from pathlib import Path
import os
import sys

def resolve_sources_path(default_name: str = "sources.yaml") -> Path:
    """
    Resolve the path to sources.yaml in a robust way:
    priority:
      1) --sources CLI arg (if you wire it up in main)
      2) ENV var SOURCES_YAML
      3) Next to this file (src/)
      4) Repo root (parent of src/)
      5) Current working directory
    Raises FileNotFoundError with a helpful message if not found.
    """
    # 1) CLI arg is intentionally handled by the caller (main) if you add it.
    # 2) ENV
    env_path = os.getenv("SOURCES_YAML")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if p.is_file():
            return p

    here = Path(__file__).resolve().parent
    candidates = [
        here / default_name,             # src/sources.yaml
        here.parent / default_name,      # repo-root/sources.yaml (if src/main.py lives under src/)
        Path.cwd() / default_name,       # current working directory
    ]

    for p in candidates:
        if p.is_file():
            return p.resolve()

    # Helpful error
    search_list = "\n".join(str(p) for p in candidates)
    raise FileNotFoundError(
        f"Could not find {default_name}. Looked in:\n{search_list}\n\n"
        f"Tips:\n"
        f"- Commit {default_name} to the repo root, or\n"
        f"- Set env SOURCES_YAML=/absolute/path/to/{default_name}, or\n"
        f"- Pass a --sources /path/to/{default_name} if you wire that up."
    )
