import hashlib

def stable_id(title, start_iso, location, url):
    key = "||".join([
        (title or "").strip().lower(),
        (start_iso or "").strip().lower(),
        (location or "").strip().lower(),
        (url or "").strip().lower()
    ])
    return hashlib.md5(key.encode("utf-8")).hexdigest()
