"""
Debug: Check different APIs to get complete trading history
"""
import requests
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

TARGET = "0xd7f85d0eb0fe0732ca38d9107ad0d4d01b1289e4"

def test_apis(address):
    print(f"Testing APIs for: {address}\n")
    
    # 1. Activity API (current)
    print("=" * 60)
    print("1. ACTIVITY API (limit=1000)")
    print("=" * 60)
    url = "https://data-api.polymarket.com/activity"
    r = requests.get(url, params={"user": address, "limit": 1000})
    data = r.json()
    print(f"Records returned: {len(data)}")
    
    if data:
        # Check date range
        timestamps = [a.get("timestamp") for a in data if a.get("timestamp")]
        if timestamps:
            from datetime import datetime
            dates = [datetime.fromtimestamp(float(ts)) for ts in timestamps]
            print(f"Date range: {min(dates).strftime('%Y-%m-%d')} to {max(dates).strftime('%Y-%m-%d')}")
        
        # Check event distribution
        events = {}
        for a in data:
            e = a.get("eventSlug", "?")
            usd = float(a.get("usdcSize", 0) or 0)
            events[e] = events.get(e, 0) + usd
        
        print("\nTop 5 events by volume:")
        for e, v in sorted(events.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"  {e[:50]}: ${v:,.0f}")
    
    # 2. Closed Positions API
    print("\n" + "=" * 60)
    print("2. CLOSED-POSITIONS API")
    print("=" * 60)
    url = "https://data-api.polymarket.com/closed-positions"
    r = requests.get(url, params={"user": address, "limit": 100})
    data = r.json()
    print(f"Records returned: {len(data)}")
    
    if data:
        print("\nTop 5 by realized PnL:")
        sorted_pos = sorted(data, key=lambda x: float(x.get("realizedPnl", 0) or 0), reverse=True)
        for p in sorted_pos[:5]:
            title = p.get("title", "?")[:50]
            pnl = float(p.get("realizedPnl", 0) or 0)
            bought = float(p.get("totalBought", 0) or 0)
            print(f"  {title}")
            print(f"    Bought: ${bought:,.0f} | PnL: ${pnl:,.0f}")
    
    # 3. Positions API (all positions including closed)
    print("\n" + "=" * 60)
    print("3. POSITIONS API")
    print("=" * 60)
    url = "https://data-api.polymarket.com/positions"
    r = requests.get(url, params={"user": address, "limit": 200, "sizeThreshold": 0})
    data = r.json()
    print(f"Records returned: {len(data)}")
    
    if data:
        print("\nTop 5 by cash PnL:")
        sorted_pos = sorted(data, key=lambda x: float(x.get("cashPnl", 0) or 0), reverse=True)
        for p in sorted_pos[:5]:
            title = p.get("title", "?")[:50]
            pnl = float(p.get("cashPnl", 0) or 0)
            cost = float(p.get("initialValue", 0) or 0)
            event = p.get("eventSlug", "?")[:40]
            print(f"  {title}")
            print(f"    Event: {event} | Cost: ${cost:,.0f} | PnL: ${pnl:,.0f}")
    
    # Summary
    print("\n" + "=" * 60)
    print("RECOMMENDATION")
    print("=" * 60)
    print("""
The Activity API only returns recent records (up to 1000).
For complete historical analysis, we should use:
- closed-positions API: Shows all closed positions with realized PnL
- positions API: Shows all positions (open and resolved) with cash PnL

We should prioritize positions/closed-positions for insider detection
since they capture the FULL trading history.
""")


if __name__ == "__main__":
    test_apis(TARGET)
