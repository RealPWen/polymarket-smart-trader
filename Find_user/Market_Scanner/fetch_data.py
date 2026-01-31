import requests
import json
import os
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

def fetch_top_markets(limit=20):
    """
    Fetches the top active markets by volume.
    """
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 100, # Fetch more to ensure we get the top ones
        "order": "volume",
        "ascending": "false"
    }
    try:
        print(f"Fetching 100 markets to sort...")
        r = requests.get(url, params=params)
        r.raise_for_status()
        markets = r.json()
        
        # Client-side sort to be sure
        markets.sort(key=lambda m: float(m.get("volume", 0) or 0), reverse=True)
        
        top_markets = markets[:limit]
        print(f"Selected top {len(top_markets)} markets. Top volume: {top_markets[0].get('volume')}")
        return top_markets
    except Exception as e:
        print(f"Error fetching markets: {e}")
        return []

def fetch_recent_trades(condition_id, limit=500):
    """
    Fetches recent trades for a given market using Data API.
    """
    url = "https://data-api.polymarket.com/trades"
    params = {"market": condition_id, "limit": limit}
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error fetching trades for {condition_id}: {e}")
        return []

def prepare_backtest_data():
    """
    Main function to download snapshot of data for backtesting.
    """
    markets = fetch_top_markets(limit=20) # Start with top 20 for speed
    
    all_data = []
    
    for i, m in enumerate(markets):
        # Use conditionId for Data API
        mid = m.get("conditionId")
        question = m.get("question")
        print(f"[{i+1}/{len(markets)}] Fetching trades for: {question} ({mid})")
        
        trades = fetch_recent_trades(mid, limit=500)
        
        market_data = {
            "market_info": m,
            "trades": trades
        }
        
        # Save individual market file
        safe_q = "".join([c for c in question if c.isalnum() or c in (' ', '-', '_')]).strip()[:50]
        fname = os.path.join(DATA_DIR, f"{i}_{safe_q}.json")
        with open(fname, "w", encoding='utf-8') as f:
            json.dump(market_data, f, indent=2)
            
        all_data.append(market_data)
        time.sleep(0.2) # Polite rate limit
        
    print("Data download complete.")

if __name__ == "__main__":
    prepare_backtest_data()
