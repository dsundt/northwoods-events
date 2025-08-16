import re
from datetime import timedelta
from typing import List, Dict, Tuple, Optional

from dateutil import parser as dp
from dateutil import tz
from ics import Calendar


def _unfold_lines(text: str) -> List[str]:
    """
    RFC5545 line unfolding: lines that begin with space or tab are continuations.
    Also normalizes CRLF/CR to LF.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    unfolded = []
    buf = ""
    for line in lines:
        if not line:
            # empty line terminates current buffer
            if buf:
                unfolded.append(buf)
                buf = ""
            unfolded.append("")  # keep empty line
            continue
        if line.startswith((" ", "\t")):
            buf += line[1:]  # continuation without the leading space
        else:
            if buf:
                unfolded.append(buf)
            buf = line
    if buf:
        unfolded.append(buf)
    return unfolded


def _blocks(text: str, begin: str, end: str) -> List[str]:
    """Extract BEGIN:… END:… blocks."""
    out = []
    start_tag = f"BEGIN:{begin}"
    end_tag = f"END:{end}"
    cur = []
    capture = False
    for line in _unfold_lines(text):
        if line.strip().upper() == start_tag:
            capture = True
            cur = [line]
            continue
        if capture:
            cur.append(line)
            if line.strip().upper() == end_tag:
                out.append("\n".join(cur))
                capture = False
                cur = []
    return out


def _parse_prop(line: str) -> Tuple[str, Dict[str, str], str]:
    """
    Parse a property line like:
      DTSTART;TZID=America/Chicago;VALUE=DATE:20250820
      SUMMARY:Title
    Returns (name_upper, params_dict, value_str)
    """
    # Split into key;params : value
    if ":" not in line:
        return line.strip().upper(), {}, ""
    lhs, val = line.split(":", 1)
    parts = lhs.split(";")
    name = parts[0].strip().upper()
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.strip().upper()] = v.strip()
        else:
            params[p.strip().upper()] = ""
    return name, params, val.strip()


def _to_dt(value: str, params: Dict[str, str]) -> Tuple[Optional[object], bool]:
    """
    Convert an ICS date/time string to a timezone-aware datetime.
    Returns (dt, is_all_day).
    Handles:
      - 20250820 (VALUE=DATE)
      - 20250820T150000
      - 20250820T150000Z
      - With TZID=…
    """
    value = value.strip()
    tzinfo = None
    if "TZID" in params:
        try:
            tzinfo = tz.gettz(params["TZID"])
        except Exception:
            tzinfo = None

    # VALUE=DATE is all-day
    is_all_day = params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value) is not None

    # If ends with Z -> UTC
    if value.endswith("Z"):
        try:
            dt = dp.parse(value)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=tz.UTC)
            return dt, is_all_day
        except Exception:
            pass

    # Try parsing as is; attach tz if specified
    try:
        dt = dp.parse(value)
        if tzinfo and not dt.tzinfo:
            dt = dt.replace(tzinfo=tzinfo)
        return dt, is_all_day
    except Exception:
        return None, is_all_day


def _lenient_parse_events(ics_text: str) -> List[Dict]:
    """
    Very tolerant VEVENT extractor.
    """
    events = []
    for block in _blocks(ics_text, "VEVENT", "VEVENT"):
        props = {}
        for line in _unfold_lines(block):
            line = line.strip()
            if not line or line.upper().startswith("BEGIN:") or line.upper().startswith("END:"):
                continue
            name, params, val = _parse_prop(line)
            # Keep last occurrence for simplicity
            props[name] = (params, val)

        title = (props.get("SUMMARY", ({}, ""))[1] or "").strip()
        desc = (props.get("DESCRIPTION", ({}, ""))[1] or "").strip()
        loc = (props.get("LOCATION", ({}, ""))[1] or "").strip()
        url = (props.get("URL", ({}, ""))[1] or "").strip()

        dtstart_raw = props.get("DTSTART", ({},""))
        dtend_raw = props.get("DTEND", ({},""))

        start, start_all_day = (None, False)
        end, end_all_day = (None, False)

        if dtstart_raw[1]:
            start, start_all_day = _to_dt(dtstart_raw[1], dtstart_raw[0])
        if dtend_raw[1]:
            end, end_all_day = _to_dt(dtend_raw[1], dtend_raw[0])

        # If no DTEND, synthesize:
        if start and not end:
            if start_all_day:
                end = start + timedelta(days=1)
            else:
                end = start + timedelta(hours=1)

        # Safety: end after start
        if start and end and end <= start:
            # bump end by 60 minutes
            end = start + timedelta(hours=1)

        # infer all_day
        all_day = False
        if start_all_day or end_all_day:
            all_day = True
        else:
            # if times are 00:00 and exactly +1 day, treat all-day
            if start and end and (end - start) >= timedelta(hours=23, minutes=59) and start.hour == 0 and start.minute == 0:
                all_day = True

        if start:
            events.append({
                "title": title,
                "url": url,
                "date_text": "",
                "venue_text": loc,
                "iso_datetime": start.isoformat(),
                "iso_end": end.isoformat() if end else None,
                "all_day_hint": all_day
            })

    return events


def parse(ics_text: str) -> List[Dict]:
    """
    Try strict ics.Calendar first; on failure, fall back to a lenient VEVENT parser.
    """
    try:
        cal = Calendar(ics_text)
        out = []
        local_tz = tz.tzlocal()
        for ev in cal.events:
            title = (ev.name or "").strip()
            url = ""
            if ev.description:
                for token in str(ev.description).split():
                    if token.startswith("http"):
                        url = token.strip()
            start = ev.begin.datetime if ev.begin else None
            end = ev.end.datetime if ev.end else None
            if start and not start.tzinfo:
                start = start.replace(tzinfo=local_tz)
            if end and not end.tzinfo:
                end = end.replace(tzinfo=local_tz)
            # Guard end > start
            if start and end and end <= start:
                end = start + timedelta(hours=1)
            out.append({
                "title": title,
                "url": url,
                "date_text": "",
                "venue_text": (ev.location or "").strip(),
                "iso_datetime": start.isoformat() if start else None,
                "iso_end": end.isoformat() if end else None,
            })
        if out:
            return out
        # if strict parse yielded nothing, try lenient
        return _lenient_parse_events(ics_text)
    except Exception:
        # Strict parse failed (your error case) -> lenient
        return _lenient_parse_events(ics_text)
