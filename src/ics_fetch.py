import re
from urllib.parse import urlparse, urlunparse
import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "(compatible; NorthwoodsBot/1.0; +https://github.com/dsundt/northwoods-events)"
)

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/calendar, text/plain, */*;q=0.8",
}

def _referer_for(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, "/", "", "", ""))

def _try_get(url: str):
    # send a realistic Referer to reduce 403s
    headers = {**HEADERS, "Referer": _referer_for(url)}
    r = requests.get(url, headers=headers, timeout=35, allow_redirects=True)
    r.raise_for_status()
    return r.text, r.headers.get("Content-Type", ""), r.url

def _modern_tribe_alternates(url: str):
    # Normalize to /events/?ical=1 when hitting a page like /festivals-events/?ical=1
    if re.search(r"/events/\?ical=1$", url):
        return [url]
    alts = []
    if "?ical=1" in url and "/events/" not in url:
        base = re.sub(r"\?.*$", "", url)
        root = url.split("/")[0] + "//" + url.split("/")[2]
        alts.append(root.rstrip("/") + "/events/?ical=1")
    # Add common variants
    alts.append(re.sub(r"\?.*$", "", url).rstrip("/") + "/?ical=1")
    alts.append(re.sub(r"\?.*$", "", url).rstrip("/") + "/?tribe_display=list&ical=1")
    return list(dict.fromkeys(alts))

def _growthzone_alternates(url: str):
    # Map any /events/... page to /events/ical
    p = urlparse(url)
    if "/events/ical" in p.path:
        return [url]
    if "/events/" in p.path:
        path = "/events/ical"
        return [urlunparse((p.scheme, p.netloc, path, "", "", ""))]
    # fallback: guess site root + /events/ical
    guess = urlunparse((p.scheme, p.netloc, "/events/ical", "", "", ""))
    return [guess]

def get_ics_text(url: str, family: str):
    """
    family: 'modern_tribe' or 'growthzone' to choose alternates.
    Returns ics_text (str). Raises the last HTTPError if all attempts fail.
    """
    tried = []
    # First try the given URL with good headers
    try:
        text, ct, final_url = _try_get(url)
        if "text/calendar" in ct.lower() or "BEGIN:VCALENDAR" in text[:2000]:
            return text
        tried.append((url, ct))
    except Exception as e:
        tried.append((url, repr(e)))

    # Try alternates
    alts = []
    if family == "modern_tribe":
        alts = _modern_tribe_alternates(url)
    elif family == "growthzone":
        alts = _growthzone_alternates(url)

    last_exc = None
    for alt in alts:
        try:
            text, ct, final_url = _try_get(alt)
            if "text/calendar" in ct.lower() or "BEGIN:VCALENDAR" in text[:2000]:
                return text
            tried.append((alt, ct))
        except Exception as e:
            last_exc = e
            tried.append((alt, repr(e)))

    # As a last resort, fetch original once more without Referer (some hosts prefer none)
    try:
        r = requests.get(url, headers=HEADERS, timeout=35, allow_redirects=True)
        r.raise_for_status()
        text = r.text
        ct = r.headers.get("Content-Type", "")
        if "text/calendar" in ct.lower() or "BEGIN:VCALENDAR" in text[:2000]:
            return text
        tried.append((url + " (no referer)", ct))
    except Exception as e:
        last_exc = e
        tried.append((url + " (no referer)", repr(e)))

    raise RuntimeError(f"ICS fetch failed. Tried: {tried}")
