import urllib.request
import urllib.error

req = urllib.request.Request(
    'https://primary-origin.sentineldr.in/',
    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
)

try:
    resp = urllib.request.urlopen(req, timeout=5)
    print('HTTP Code:', resp.status)
    print('Headers:', dict(resp.headers))
    print('Body preview:', resp.read().decode('utf-8')[:500])
except urllib.error.HTTPError as e:
    print('HTTP Code:', e.code)
    print('Headers:', dict(e.headers))
    print('Body preview:', e.read().decode('utf-8')[:500])
except Exception as e:
    print('Error:', e)
