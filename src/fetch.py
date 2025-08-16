import time, random, requests

UA = "Mozilla/5.0 (compatible; NorthwoodsBot/1.0; +https://github.com/dsundt/northwoods-events)"

def get(url, timeout=20, max_retries=4):
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt + random.random())
