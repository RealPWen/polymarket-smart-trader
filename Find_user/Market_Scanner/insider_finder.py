"""
Insider Finder v4 - Anomaly-Based Detection

Core Insight: Insider trading is about ANOMALIES relative to the user's OWN normal behavior.

Key Signals:
1. VOLUME ANOMALY: One event has way more volume than others
   - If avg event volume is $1K, but one event has $100K = suspicious
   - Concentration Ratio = max_event_volume / total_volume

2. TIMING ANOMALY: Sudden burst of activity in short window
   - Normally trades $1K/week, suddenly trades $100K in 3 days = suspicious
   - Compare peak period volume vs normal period volume

3. SIZE ANOMALY: Trade sizes during "insider period" are much larger
   - Normal trade size: $500
   - Insider period trade size: $50,000
   - This suggests they had specific high-conviction info
"""

import requests
import json
import time
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_leaderboard(limit=50, time_period="ALL", offset=0):
    url = "https://data-api.polymarket.com/v1/leaderboard"
    params = {"timePeriod": time_period, "orderBy": "PNL", "limit": min(limit, 50), "offset": offset}
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error: {e}")
        return []


def fetch_activity(address, limit=1000):
    """Fetches recent activity (limited, may miss historical trades)."""
    url = "https://data-api.polymarket.com/activity"
    params = {"user": address, "limit": limit}
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()
    except:
        return []


def fetch_closed_positions(address, limit=100):
    """
    Fetches closed positions - this gives COMPLETE historical trading record.
    Much better than activity API for analyzing full trading history.
    """
    url = "https://data-api.polymarket.com/closed-positions"
    params = {"user": address, "limit": limit}
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()
    except:
        return []


def detect_volume_anomaly(activity):
    """
    Metric 1: Is there ONE event with dramatically higher volume than others?
    
    Insider has specific info about ONE event, so they concentrate capital there.
    
    Calculation:
    - Volume per event
    - If max_event_volume > 5x median_event_volume = suspicious
    - Concentration Ratio = max_event_volume / total_volume
    """
    if not activity:
        return 0, {}
    
    # Calculate volume per event
    volume_by_event = defaultdict(float)
    for a in activity:
        if a.get("type") == "TRADE":
            event = a.get("eventSlug", "unknown")
            usd = float(a.get("usdcSize", 0) or 0)
            volume_by_event[event] += usd
    
    if len(volume_by_event) < 2:
        return 0, {"error": "Too few events to compare"}
    
    volumes = list(volume_by_event.values())
    total_volume = sum(volumes)
    max_volume = max(volumes)
    median_volume = statistics.median(volumes)
    mean_volume = statistics.mean(volumes)
    
    # Find the top event
    top_event = max(volume_by_event.items(), key=lambda x: x[1])
    
    details = {
        "total_events": len(volume_by_event),
        "total_volume": round(total_volume, 0),
        "max_event_volume": round(max_volume, 0),
        "median_event_volume": round(median_volume, 0),
        "mean_event_volume": round(mean_volume, 0),
        "top_event": top_event[0][:40],
        "top_event_volume": round(top_event[1], 0)
    }
    
    score = 0
    
    # Concentration Ratio: How much of total is in top event?
    concentration = max_volume / total_volume if total_volume > 0 else 0
    details["concentration_ratio"] = round(concentration, 3)
    
    if concentration > 0.8:
        score += 50  # 80%+ in one event = very suspicious
        details["signal"] = "EXTREME_CONCENTRATION"
    elif concentration > 0.6:
        score += 35
        details["signal"] = "HIGH_CONCENTRATION"
    elif concentration > 0.4:
        score += 20
        details["signal"] = "MODERATE_CONCENTRATION"
    
    # Anomaly Ratio: Is top event way bigger than typical?
    if median_volume > 0:
        anomaly_ratio = max_volume / median_volume
        details["anomaly_ratio"] = round(anomaly_ratio, 1)
        
        if anomaly_ratio > 20:
            score += 40  # Top event is 20x bigger than median
            details["anomaly_signal"] = "EXTREME_ANOMALY"
        elif anomaly_ratio > 10:
            score += 25
            details["anomaly_signal"] = "HIGH_ANOMALY"
        elif anomaly_ratio > 5:
            score += 15
            details["anomaly_signal"] = "MODERATE_ANOMALY"
    
    return score, details


def detect_timing_anomaly(activity):
    """
    Metric 2: Was there a sudden burst of high-volume trading?
    
    Insider suddenly trades heavily in short window, then stops.
    
    Calculation:
    - Group activity by week
    - Find peak week volume vs average week volume
    - If peak >> average = suspicious
    """
    if not activity:
        return 0, {}
    
    # Group by week
    volume_by_week = defaultdict(float)
    trades_by_week = defaultdict(int)
    
    for a in activity:
        if a.get("type") == "TRADE":
            ts = a.get("timestamp")
            usd = float(a.get("usdcSize", 0) or 0)
            if ts:
                try:
                    dt = datetime.fromtimestamp(float(ts))
                    week_key = dt.strftime("%Y-W%W")
                    volume_by_week[week_key] += usd
                    trades_by_week[week_key] += 1
                except:
                    pass
    
    if len(volume_by_week) == 0:
        return 0, {"error": "No trading activity"}
    
    # Special case: Only 1-2 weeks of activity = extremely suspicious one-shot pattern
    if len(volume_by_week) <= 2:
        total_vol = sum(volume_by_week.values())
        weeks_list = list(volume_by_week.keys())
        return 50, {
            "total_weeks_active": len(volume_by_week),
            "weeks": weeks_list,
            "total_volume": round(total_vol, 0),
            "timing_signal": "ONE_SHOT_TRADER",
            "note": "Only 1-2 weeks of activity = highly suspicious"
        }
    
    weeks = list(volume_by_week.keys())
    volumes = list(volume_by_week.values())
    
    peak_week = max(volume_by_week.items(), key=lambda x: x[1])
    total_volume = sum(volumes)
    mean_weekly = statistics.mean(volumes)
    median_weekly = statistics.median(volumes) if len(volumes) > 1 else volumes[0]
    
    details = {
        "total_weeks_active": len(weeks),
        "peak_week": peak_week[0],
        "peak_week_volume": round(peak_week[1], 0),
        "peak_week_trades": trades_by_week[peak_week[0]],
        "mean_weekly_volume": round(mean_weekly, 0),
        "median_weekly_volume": round(median_weekly, 0)
    }
    
    score = 0
    
    # Peak week vs median week
    if median_weekly > 0:
        burst_ratio = peak_week[1] / median_weekly
        details["burst_ratio"] = round(burst_ratio, 1)
        
        if burst_ratio > 20:
            score += 40
            details["timing_signal"] = "EXTREME_BURST"
        elif burst_ratio > 10:
            score += 25
            details["timing_signal"] = "HIGH_BURST"
        elif burst_ratio > 5:
            score += 15
            details["timing_signal"] = "MODERATE_BURST"
    
    # Check if peak week is isolated (not adjacent to other high-volume weeks)
    # This would indicate a one-time insider bet vs consistent trading
    sorted_weeks = sorted(volume_by_week.items(), key=lambda x: x[0])
    peak_idx = next(i for i, (w, v) in enumerate(sorted_weeks) if w == peak_week[0])
    
    # Check isolation: peak should be >> neighbors
    neighbors = []
    if peak_idx > 0:
        neighbors.append(sorted_weeks[peak_idx - 1][1])
    if peak_idx < len(sorted_weeks) - 1:
        neighbors.append(sorted_weeks[peak_idx + 1][1])
    
    if neighbors:
        max_neighbor = max(neighbors)
        if max_neighbor > 0 and peak_week[1] / max_neighbor > 5:
            score += 15
            details["isolated_burst"] = True
    
    return score, details


def detect_size_anomaly(activity):
    """
    Metric 3: Are there trades with anomalously large sizes?
    
    Insider makes a few LARGE trades (high conviction) vs many small trades.
    
    Calculation:
    - Compare largest trade sizes to median trade size
    - If max_trade > 10x median_trade = suspicious
    """
    if not activity:
        return 0, {}
    
    # Get all trade sizes
    trade_sizes = []
    for a in activity:
        if a.get("type") == "TRADE":
            usd = float(a.get("usdcSize", 0) or 0)
            if usd > 0:
                trade_sizes.append({
                    "usd": usd,
                    "event": a.get("eventSlug", "")[:30],
                    "title": a.get("title", "")[:40]
                })
    
    if len(trade_sizes) < 5:
        return 0, {"error": "Too few trades"}
    
    sizes = [t["usd"] for t in trade_sizes]
    median_size = statistics.median(sizes)
    mean_size = statistics.mean(sizes)
    max_size = max(sizes)
    
    # Find top 3 largest trades
    top_trades = sorted(trade_sizes, key=lambda x: x["usd"], reverse=True)[:3]
    
    details = {
        "total_trades": len(trade_sizes),
        "median_trade_size": round(median_size, 0),
        "mean_trade_size": round(mean_size, 0),
        "max_trade_size": round(max_size, 0),
        "top_trades": [
            {"size": round(t["usd"], 0), "event": t["event"]} 
            for t in top_trades
        ]
    }
    
    score = 0
    
    # Size anomaly ratio
    if median_size > 0:
        size_anomaly = max_size / median_size
        details["size_anomaly_ratio"] = round(size_anomaly, 1)
        
        if size_anomaly > 50:
            score += 30
            details["size_signal"] = "EXTREME_SIZE_ANOMALY"
        elif size_anomaly > 20:
            score += 20
            details["size_signal"] = "HIGH_SIZE_ANOMALY"
        elif size_anomaly > 10:
            score += 10
            details["size_signal"] = "MODERATE_SIZE_ANOMALY"
    
    return score, details


def calculate_insider_score_v4(user_data, activity):
    """
    Combined Insider Score based on anomaly detection.
    """
    total_score = 0
    all_metrics = {}
    
    # Basic stats
    pnl = float(user_data.get("pnl", 0) or 0)
    vol = float(user_data.get("vol", 0) or 0)
    roi = pnl / vol if vol > 0 else 0
    
    all_metrics["leaderboard"] = {
        "pnl": round(pnl, 0),
        "volume": round(vol, 0),
        "roi": round(roi, 3)
    }
    
    # High ROI bonus (but not main signal)
    if roi > 0.4:
        total_score += 15
    elif roi > 0.25:
        total_score += 10
    
    # Metric 1: Volume Anomaly (most important)
    score1, details1 = detect_volume_anomaly(activity)
    total_score += score1
    if details1:
        all_metrics["volume_anomaly"] = details1
    
    # Metric 2: Timing Anomaly
    score2, details2 = detect_timing_anomaly(activity)
    total_score += score2
    if details2:
        all_metrics["timing_anomaly"] = details2
    
    # Metric 3: Size Anomaly
    score3, details3 = detect_size_anomaly(activity)
    total_score += score3
    if details3:
        all_metrics["size_anomaly"] = details3
    
    # Dormancy check (still relevant as secondary signal)
    trade_timestamps = []
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
        if days_dormant > 60:
            total_score += 15
            all_metrics["dormant_days"] = days_dormant
    
    return total_score, all_metrics


def analyze_closed_positions(closed_positions):
    """
    Analyze closed positions for insider patterns.
    This uses the closed-positions API which has COMPLETE history.
    
    Key metrics:
    - Volume concentration by event
    - PnL concentration by event  
    - Number of events traded
    """
    if not closed_positions:
        return 0, {"error": "No closed positions"}
    
    score = 0
    details = {}
    
    # Group by event
    by_event = {}
    for p in closed_positions:
        event = p.get("eventSlug", "unknown")
        if event not in by_event:
            by_event[event] = {"bought": 0, "pnl": 0, "positions": 0}
        
        by_event[event]["bought"] += float(p.get("totalBought", 0) or 0)
        by_event[event]["pnl"] += float(p.get("realizedPnl", 0) or 0)
        by_event[event]["positions"] += 1
    
    # Calculate totals
    total_bought = sum(e["bought"] for e in by_event.values())
    total_pnl = sum(e["pnl"] for e in by_event.values())
    
    # Find top event by volume
    top_event = max(by_event.items(), key=lambda x: x[1]["bought"])
    
    details["total_events"] = len(by_event)
    details["total_bought"] = round(total_bought, 0)
    details["total_pnl"] = round(total_pnl, 0)
    details["top_event"] = top_event[0][:40]
    details["top_event_bought"] = round(top_event[1]["bought"], 0)
    details["top_event_pnl"] = round(top_event[1]["pnl"], 0)
    
    # Concentration ratio (by invested capital)
    if total_bought > 0:
        concentration = top_event[1]["bought"] / total_bought
        details["concentration_ratio"] = round(concentration, 3)
        
        if concentration > 0.7:
            score += 50
            details["signal"] = "EXTREME_CONCENTRATION"
        elif concentration > 0.5:
            score += 35
            details["signal"] = "HIGH_CONCENTRATION"
        elif concentration > 0.3:
            score += 20
            details["signal"] = "MODERATE_CONCENTRATION"
    
    # Low number of events = focused insider
    if len(by_event) <= 3:
        score += 30
        details["event_focus"] = "HIGHLY_FOCUSED"
    elif len(by_event) <= 5:
        score += 15
        details["event_focus"] = "FOCUSED"
    
    # High ROI on top event
    if top_event[1]["bought"] > 0:
        event_roi = top_event[1]["pnl"] / top_event[1]["bought"]
        details["top_event_roi"] = round(event_roi, 3)
        
        if event_roi > 0.5 and top_event[1]["bought"] > 100000:
            score += 25
            details["high_conviction_win"] = True
    
    return score, details


def run_insider_finder_v4(top_n=50):
    """Main analysis function."""
    print("=" * 70)
    print("INSIDER FINDER v4 - Anomaly-Based Detection")
    print("=" * 70)
    
    leaderboard = fetch_leaderboard(limit=top_n, time_period="ALL")
    
    if not leaderboard:
        print("Failed to fetch leaderboard.")
        return
    
    print(f"\nAnalyzing {len(leaderboard)} users...\n")
    
    results = []
    
    for i, user in enumerate(leaderboard):
        address = user.get("proxyWallet")
        name = user.get("userName") or (address[:10] if address else "?")
        
        if not address:
            continue
        
        print(f"[{i+1}/{len(leaderboard)}] {name}", end=" ")
        
        # Fetch both activity and closed positions
        activity = fetch_activity(address, limit=500)
        closed_positions = fetch_closed_positions(address, limit=100)
        
        # Calculate score from activity (recent data)
        score, metrics = calculate_insider_score_v4(user, activity)
        
        # Add score from closed positions (complete history)
        cp_score, cp_details = analyze_closed_positions(closed_positions)
        score += cp_score
        if cp_details and "error" not in cp_details:
            metrics["closed_positions"] = cp_details
        
        print(f"-> Score: {score}")
        
        results.append({
            "rank": int(user.get("rank", i+1)),
            "address": address,
            "name": name,
            "insider_score": score,
            "metrics": metrics
        })
        
        time.sleep(0.4)  # Slightly longer delay for 2 API calls
    
    # Sort by score
    results.sort(key=lambda x: x["insider_score"], reverse=True)
    
    # Output
    print("\n" + "=" * 70)
    print("TOP INSIDER CANDIDATES (v4 - Anomaly Detection)")
    print("=" * 70)
    
    for r in results[:15]:
        if r["insider_score"] >= 50:
            print(f"\n{'='*60}")
            print(f"[SCORE: {r['insider_score']}] {r['name']} (Rank #{r['rank']})")
            print(f"Address: {r['address']}")
            
            m = r["metrics"]
            lb = m.get("leaderboard", {})
            print(f"PnL: ${lb.get('pnl', 0):,.0f} | Volume: ${lb.get('volume', 0):,.0f} | ROI: {lb.get('roi', 0):.1%}")
            
            if "volume_anomaly" in m:
                va = m["volume_anomaly"]
                print(f"\n[VOLUME ANOMALY]")
                print(f"  Concentration: {va.get('concentration_ratio', 0):.0%} in top event")
                print(f"  Top Event: {va.get('top_event', '?')} (${va.get('top_event_volume', 0):,.0f})")
                print(f"  Anomaly Ratio: {va.get('anomaly_ratio', 0):.1f}x vs median event")
                if va.get("signal"):
                    print(f"  Signal: {va.get('signal')}")
            
            if "timing_anomaly" in m:
                ta = m["timing_anomaly"]
                print(f"\n[TIMING ANOMALY]")
                print(f"  Peak Week: {ta.get('peak_week')} (${ta.get('peak_week_volume', 0):,.0f})")
                print(f"  Burst Ratio: {ta.get('burst_ratio', 0):.1f}x vs median week")
                if ta.get("timing_signal"):
                    print(f"  Signal: {ta.get('timing_signal')}")
            
            if "size_anomaly" in m:
                sa = m["size_anomaly"]
                print(f"\n[SIZE ANOMALY]")
                print(f"  Max Trade: ${sa.get('max_trade_size', 0):,.0f} vs Median: ${sa.get('median_trade_size', 0):,.0f}")
                print(f"  Size Ratio: {sa.get('size_anomaly_ratio', 0):.1f}x")
            
            if m.get("dormant_days"):
                print(f"\n[DORMANT] {m['dormant_days']} days since last trade")
    
    # Save
    output_path = os.path.join(OUTPUT_DIR, "insider_candidates_v4.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n\nResults saved to: {output_path}")
    
    return results


if __name__ == "__main__":
    run_insider_finder_v4(top_n=50)
