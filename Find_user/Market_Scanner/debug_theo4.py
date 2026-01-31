"""
Debug Script: Deep Analysis of Theo4's Trading Pattern
"""
import requests
import json
import sys
from datetime import datetime
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

# Theo4's address (from leaderboard)
def get_theo4_address():
    url = "https://data-api.polymarket.com/v1/leaderboard"
    params = {"timePeriod": "ALL", "orderBy": "PNL", "limit": 1}
    r = requests.get(url, params=params)
    data = r.json()
    if data:
        return data[0].get("proxyWallet"), data[0]
    return None, None

def fetch_all_positions(address):
    """Fetch ALL positions, not just 100"""
    url = "https://data-api.polymarket.com/positions"
    params = {"user": address, "limit": 500, "sizeThreshold": 0}
    r = requests.get(url, params=params)
    return r.json()

def fetch_all_activity(address):
    """Fetch ALL activity"""
    url = "https://data-api.polymarket.com/activity"
    params = {"user": address, "limit": 1000}
    r = requests.get(url, params=params)
    return r.json()

def fetch_closed_positions(address):
    """Fetch closed/resolved positions"""
    url = "https://data-api.polymarket.com/closed-positions"
    params = {"user": address, "limit": 500}
    try:
        r = requests.get(url, params=params)
        return r.json()
    except:
        return []

def analyze_theo4():
    print("=" * 70)
    print("DEEP ANALYSIS: Theo4")
    print("=" * 70)
    
    address, user_data = get_theo4_address()
    if not address:
        print("Could not find Theo4")
        return
    
    print(f"\nAddress: {address}")
    print(f"PnL: ${user_data.get('pnl'):,.2f}")
    print(f"Volume: ${user_data.get('vol'):,.2f}")
    print(f"ROI: {user_data.get('pnl') / user_data.get('vol') * 100:.1f}%")
    
    # Fetch data
    print("\nFetching positions...")
    positions = fetch_all_positions(address)
    print(f"Found {len(positions)} positions")
    
    print("Fetching activity...")
    activity = fetch_all_activity(address)
    print(f"Found {len(activity)} activity records")
    
    print("Fetching closed positions...")
    closed = fetch_closed_positions(address)
    print(f"Found {len(closed)} closed positions")
    
    # =========================================================================
    # ANALYSIS 1: Position Details
    # =========================================================================
    print("\n" + "=" * 70)
    print("ANALYSIS 1: ALL POSITIONS")
    print("=" * 70)
    
    # Sort by PnL
    positions_sorted = sorted(positions, key=lambda x: float(x.get("cashPnl", 0) or 0), reverse=True)
    
    total_pnl = 0
    winning_positions = []
    
    for i, p in enumerate(positions_sorted[:20]):  # Top 20
        title = p.get("title", "Unknown")[:50]
        avg_price = float(p.get("avgPrice", 0) or 0)
        cur_price = float(p.get("curPrice", 0) or 0)
        size = float(p.get("size", 0) or 0)
        cash_pnl = float(p.get("cashPnl", 0) or 0)
        event_slug = p.get("eventSlug", "")[:30]
        outcome = p.get("outcome", "?")
        
        total_pnl += cash_pnl
        
        # Calculate profit multiple
        profit_mult = (cur_price - avg_price) / avg_price if avg_price > 0 else 0
        
        status = "[RESOLVED]" if cur_price in [0, 1] else "[OPEN]"
        win_lose = "WIN" if cur_price == 1 and size > 0 else ("LOSE" if cur_price == 0 and size > 0 else "?")
        
        print(f"\n#{i+1} {status} {win_lose}")
        print(f"  {title}")
        print(f"  Outcome: {outcome} | Entry: {avg_price:.3f} | Final: {cur_price:.2f}")
        print(f"  Size: {size:.0f} | PnL: ${cash_pnl:,.2f} | Multiple: {profit_mult:.1f}x")
        print(f"  Event: {event_slug}")
        
        if cash_pnl > 0:
            winning_positions.append(p)
    
    # =========================================================================
    # ANALYSIS 2: Event Clustering
    # =========================================================================
    print("\n" + "=" * 70)
    print("ANALYSIS 2: EVENT CLUSTERING")
    print("=" * 70)
    
    by_event = defaultdict(list)
    for p in positions:
        event = p.get("eventSlug", "unknown")
        by_event[event].append(p)
    
    # Sort events by total PnL
    event_pnl = []
    for event, ps in by_event.items():
        total = sum(float(p.get("cashPnl", 0) or 0) for p in ps)
        event_pnl.append((event, ps, total))
    
    event_pnl.sort(key=lambda x: x[2], reverse=True)
    
    for event, ps, pnl in event_pnl[:10]:
        if abs(pnl) > 100:
            print(f"\n[{event}] Markets: {len(ps)} | PnL: ${pnl:,.2f}")
            for p in ps:
                title = p.get("title", "?")[:40]
                outcome = p.get("outcome", "?")
                entry = float(p.get("avgPrice", 0) or 0)
                final = float(p.get("curPrice", 0) or 0)
                size = float(p.get("size", 0) or 0)
                print(f"  - {outcome} @ {entry:.2f} (size: {size:.0f}) -> {final}")
    
    # =========================================================================
    # ANALYSIS 3: Trading Timeline
    # =========================================================================
    print("\n" + "=" * 70)
    print("ANALYSIS 3: TRADING TIMELINE")
    print("=" * 70)
    
    # Group activity by date
    by_date = defaultdict(list)
    for a in activity:
        ts = a.get("timestamp")
        if ts:
            try:
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromtimestamp(float(ts))
                date_str = dt.strftime("%Y-%m-%d")
                by_date[date_str].append(a)
            except:
                pass
    
    # Sort dates
    dates = sorted(by_date.keys())
    
    print(f"\nTrading active on {len(dates)} days")
    if dates:
        print(f"First activity: {dates[0]}")
        print(f"Last activity: {dates[-1]}")
        
        # Show activity volume by date
        print("\nDaily Activity (last 30 days or all if less):")
        for date in dates[-30:]:
            count = len(by_date[date])
            total_val = sum(float(a.get("value", 0) or 0) for a in by_date[date])
            print(f"  {date}: {count} trades, ${total_val:,.0f} volume")
    
    # =========================================================================
    # ANALYSIS 4: Low-Odds Wins Detail
    # =========================================================================
    print("\n" + "=" * 70)
    print("ANALYSIS 4: LOW-ODDS WINS (Bought < 0.3, Won)")
    print("=" * 70)
    
    low_odds_wins = []
    for p in positions:
        avg_price = float(p.get("avgPrice", 0) or 0)
        cur_price = float(p.get("curPrice", 0) or 0)
        size = float(p.get("size", 0) or 0)
        cash_pnl = float(p.get("cashPnl", 0) or 0)
        
        if avg_price < 0.3 and cur_price == 1 and size > 0:
            low_odds_wins.append(p)
    
    print(f"\nFound {len(low_odds_wins)} low-odds winning positions:")
    for p in sorted(low_odds_wins, key=lambda x: float(x.get("cashPnl", 0) or 0), reverse=True):
        title = p.get("title", "?")[:50]
        entry = float(p.get("avgPrice", 0) or 0)
        pnl = float(p.get("cashPnl", 0) or 0)
        mult = (1 - entry) / entry if entry > 0 else 0
        print(f"  - {title}")
        print(f"    Entry: {entry:.3f} | PnL: ${pnl:,.2f} | {mult:.1f}x return")
    
    # =========================================================================
    # SAVE RAW DATA
    # =========================================================================
    output = {
        "address": address,
        "user_data": user_data,
        "positions": positions,
        "activity": activity[:100],  # First 100 for size
        "closed_positions": closed
    }
    
    with open("output/theo4_debug.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    
    print("\n\nRaw data saved to output/theo4_debug.json")

if __name__ == "__main__":
    analyze_theo4()
