import requests
import json
import sys

def test_fetch(mid, label):
    print(f"Testing {label}: {mid}")
    url = "https://gamma-api.polymarket.com/trades"
    params = {"market": mid, "limit": 5}
    try:
        r = requests.get(url, params=params)
        print(f"Status: {r.status_code}")
        print(f"Headers: {r.headers.get('content-type')}")
        print(f"Preview: {r.text[:200]}")
        data = r.json()
        print(f"Result count: {len(data)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    int_id = "1279575"
    test_fetch(int_id, "Integer ID")
