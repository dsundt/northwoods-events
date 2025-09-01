# src/utils.py
import json
import os
import re
import pathlib
from typing import Optional, Any, Dict

import dateparser
from dateutil import tz


def clean_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def slugify(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return slug or None


def _to_utc_iso(dtobj) -> Optional[str]:
    if not dtobj:
        return None
    if getattr(dtobj, "tzinfo", None) is None:
        dtobj = dtobj.replace(tzinfo=tz.UTC)
    dt_utc = dtobj.astimezone(tz.UTC)
    # Keep seconds for stability
    return dt_utc.isoformat().replace("+00:00", "Z")


def parse_date(s: Optional[str], tzname: Optional[str]) -> Optional[str]:
    """
    Parse free-form date/time to an ISO UTC string.
    """
    if not s:
        return None
    settings = {
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": None,
        "TIMEZONE": tzname or "UTC",
        "TO_TIMEZONE": "UTC",
    }
    dtobj = dateparser.parse(s, settings=settings)
    return _to_utc_iso(dtobj)


def norm_event(
    *,
    source: Optional[str],
    title: Optional[str],
    url: Optional[str],
    start: Optional[str],
    end: Optional[str],
    tzname: Optional[str],
    location: Optional[str],
    city: Optional[str],
    description: Optional[str],
    image: Optional[str],
) -> Dict[str, Any]:
    """
    Normalize to a consistent event dict. `start`/`end` may already be ISO;
    if not, we'll try to parse them. Always store ISO in UTC.
    """
    start_iso = start if (start and re.search(r"^\d{4}-\d", start)) else parse_date(start, tzname)
    end_iso = end if (end and re.search(r"^\d{4}-\d", end)) else parse_date(end, tzname)

    return {
        "source": clean_text(source),
        "title": clean_text(title),
        "url": url,
        "start": start_iso,
        "end": end_iso,
        "tzname": tzname,
        "location": clean_text(location),
        "city": clean_text(city),
        "description": clean_text(description),
        "image": image,
    }


def save_debug_html(name: str, html: str, state_dir: str = "state") -> None:
    """
    When a parser yields zero events, save the raw HTML for quick diagnosis.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "unknown").lower()).strip("-") or "unknown"
    p = pathlib.Path(state_dir, "html")
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{slug}.html").write_text(html or "", encoding="utf-8")
