import time, random, requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 " \
     "(compatible; NorthwoodsBot/1.0; +https://github.com/dsundt/northwoods-events)"

COMMON_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

def get(url, timeout=25, max_retries=4):
    last_exc = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=COMMON_HEADERS, timeout=timeout, allow_redirects=True)
            text = r.text or ""
            # crude bot/challenge detection
            if any(k in text.lower() for k in [
                "cf-chl", "cloudflare", "attention required", "captcha", "enable cookies"
            ]) and r.status_code != 200:
                # try again with backoff
                raise RuntimeError(f"Possible challenge page (status {r.status_code})")
            r.raise_for_status()
            return text, r.url, r.status_code
        except Exception as e:
            last_exc = e
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt + random.random())
    raise last_exc
