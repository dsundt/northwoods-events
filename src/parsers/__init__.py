# src/parsers/__init__.py
# Keep this package lightweight; don't import submodules here.
# Main code should import parsers.modern_tribe, parsers.growthzone, etc. directly.

__all__ = ["modern_tribe", "growthzone", "simpleview", "municipal", "_text"]
