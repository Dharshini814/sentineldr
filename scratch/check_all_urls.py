import urllib.request
import urllib.error

for url in [
    'https://primary-origin.sentineldr.in/',
    'https://backup-origin.sentineldr.in/',
    'https://portfolio.sentineldr.in/',
    'http://localhost:8000/',
    'http://10.64.251.44:8001/'
]:
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=4)
        print(f"[{url}] -> HTTP {resp.status} (OK)")
    except urllib.error.HTTPError as e:
        print(f"[{url}] -> HTTP {e.code} ({e.reason})")
    except Exception as e:
        print(f"[{url}] -> FAILED: {e}")
