import requests
import json
import sys

def get_first_active_market():
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 1,
        "order": "volume",
        "ascending": "false"
    }
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if data:
            return data[0]['id']
    except:
        pass
    return None

def check_trade(market_id):
    if not market_id:
        print("No market found")
        return

    print(f"Checking trades for market: {market_id}")
    url = "https://gamma-api.polymarket.com/trades"
    params = {"market": market_id, "limit": 1}
    try:
        r = requests.get(url, params=params)
        data = r.json()
        if data:
            print(json.dumps(data[0], indent=2))
        else:
            print("No trades found.")
    except Exception as e:
        print(e)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    mid = get_first_active_market()
    check_trade(mid)
