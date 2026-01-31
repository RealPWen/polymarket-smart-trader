"""
Debug: Analyze a specific insider candidate (Updated for v4 with Closed Positions)
"""
import requests
import json
import sys
from datetime import datetime
from collections import defaultdict
import statistics

# Import updated logic
from insider_finder import (
    detect_volume_anomaly, 
    detect_timing_anomaly, 
    detect_size_anomaly, 
    analyze_closed_positions,
    fetch_activity,
    fetch_closed_positions
)

sys.stdout.reconfigure(encoding='utf-8')

TARGET_ADDRESS = "0xd82079c0d6b837bad90abf202befc079da5819f6"

def analyze_wallet(address):
    print("=" * 70)
    print(f"ANALYZING: {address}")
    print("=" * 70)
    
    # 1. Fetch Data
    print("\nFetching data...")
    activity = fetch_activity(address, limit=1000)
    closed_pos = fetch_closed_positions(address, limit=100)
    
    print(f"Activity Records: {len(activity)}")
    print(f"Closed Positions: {len(closed_pos)}")
    
    # 2. Activity Analysis (Recent/Detailed)
    if activity:
        print("\n" + "-" * 30)
        print("ACTIVITY ANALYSIS")
        print("-" * 30)
        
        score1, details1 = detect_volume_anomaly(activity)
        score2, details2 = detect_timing_anomaly(activity)
        score3, details3 = detect_size_anomaly(activity)
        
        print(f"Volume Score: {score1}")
        if "top_event" in details1:
            print(f"  Top Event: {details1['top_event']} (${details1.get('top_event_volume',0):,.0f})")
            print(f"  Concentration: {details1.get('concentration_ratio',0):.1%}")
            
        print(f"Timing Score: {score2}")
        if "peak_week" in details2:
            print(f"  Peak Week: {details2['peak_week']}")
            
        print(f"Size Score: {score3}")
        if "max_trade_size" in details3:
             print(f"  Max Trade: ${details3['max_trade_size']:,.0f}")

    # 3. Closed Positions Analysis (Historical/Profit)
    print("\n" + "-" * 30)
    print("CLOSED POSITIONS ANALYSIS")
    print("-" * 30)
    
    score_cp, details_cp = analyze_closed_positions(closed_pos)
    print(f"Closed Positions Score: {score_cp}")
    
    if details_cp:
        print(f"  Total PnL: ${details_cp.get('total_pnl', 0):,.0f}")
        print(f"  Total Bought: ${details_cp.get('total_bought', 0):,.0f}")
        print(f"  Top Event: {details_cp.get('top_event')}")
        print(f"  Top Event PnL: ${details_cp.get('top_event_pnl', 0):,.0f}")
        if "concentration_ratio" in details_cp:
            print(f"  Concentration: {details_cp['concentration_ratio']:.1%}")
    
    # 4. Total Score
    total_score = 0
    if activity:
        total_score += score1 + score2 + score3
    total_score += score_cp
    
    # Check dormancy
    dormant_score = 0
    trade_timestamps = []
    if activity:
        for a in activity:
            if a.get("type") == "TRADE":
                ts = a.get("timestamp")
                if ts:
                    try:
                        trade_timestamps.append(datetime.fromtimestamp(float(ts)))
                    except:
                        pass
    
    if trade_timestamps:
        last_trade = max(trade_timestamps)
        days_dormant = (datetime.now() - last_trade).days
        print(f"\nDays Dormant: {days_dormant}")
        if days_dormant > 60:
            dormant_score = 15
            print("  (+15 points for dormancy)")
            
    total_score += dormant_score

    print("\n" + "=" * 70)
    print(f"TOTAL INSIDER SCORE: {total_score}")
    print("=" * 70)
    
    # Save debug output
    debug_data = {
        "address": address,
        "scores": {
            "volume": score1 if activity else 0,
            "timing": score2 if activity else 0,
            "size": score3 if activity else 0,
            "closed_positions": score_cp,
            "dormancy": dormant_score,
            "total": total_score
        },
        "details": {
            "volume": details1 if activity else {},
            "timing": details2 if activity else {},
            "size": details3 if activity else {},
            "closed_positions": details_cp
        }
    }
    
    with open("output/debug_single_wallet.json", "w", encoding="utf-8") as f:
        json.dump(debug_data, f, indent=2, default=str)
    print("Saved details to output/debug_single_wallet.json")

if __name__ == "__main__":
    analyze_wallet(TARGET_ADDRESS)
