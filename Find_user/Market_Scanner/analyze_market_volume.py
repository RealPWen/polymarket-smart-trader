import requests
import json
import os
import sys

# Add parent directory to path to allow importing utils if needed (though keeping this standalone for now)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def fetch_top_volume_markets(limit=100):
    """
    Fetches active markets sorted by volume from Polymarket (Gamma API).
    """
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": "volume",
        "ascending": "false"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        print(f"Error fetching markets: {e}")
        return []

def analyze_volume_distribution(markets):
    """
    Analyzes the volume distribution to determine a good cutoff for 'Top X'.
    """
    if not markets:
        print("No markets found.")
        return

    print(f"Analyzing Top {len(markets)} Markets by Volume...\n")
    
    total_volume_all = sum(float(m.get("volume", 0) or 0) for m in markets)
    
    cumulative_volume = 0
    print(f"{'Rank':<5} {'Market ID':<10} {'Volume':<15} {'Cumul. %':<10} {'Question'}")
    print("-" * 100)
    
    cutoff_points = []
    
    for i, m in enumerate(markets):
        vol = float(m.get("volume", 0) or 0)
        cumulative_volume += vol
        percentage = (cumulative_volume / total_volume_all) * 100
        
        # Capture cutoff points for 50%, 80%, 90% volume concentration
        if percentage >= 50 and not any(c['label'] == '50%' for c in cutoff_points):
            cutoff_points.append({'label': '50%', 'rank': i + 1})
        if percentage >= 80 and not any(c['label'] == '80%' for c in cutoff_points):
            cutoff_points.append({'label': '80%', 'rank': i + 1})
        if percentage >= 90 and not any(c['label'] == '90%' for c in cutoff_points):
            cutoff_points.append({'label': '90%', 'rank': i + 1})
            
        if i < 20: # Print detailed top 20
            print(f"{i+1:<5} {m.get('id', '')[:8]:<10} ${vol:,.0f}<15 {percentage:.1f}%      {m.get('question', '')[:50]}")
            
    print("-" * 100)
    print(f"\nStats:")
    print(f"Total Volume of Top {len(markets)}: ${total_volume_all:,.0f}")
    if cutoff_points:
        print("Concentration Cutoffs:")
        for c in cutoff_points:
            print(f"  - Top {c['rank']} markets account for {c['label']} of the volume.")
    else:
        print("Detailed cutoff calculation requires more data.")

if __name__ == "__main__":
    # Force UTF-8 encoding for Windows console (emoji safety etc)
    sys.stdout.reconfigure(encoding='utf-8')
    
    # Fetch a bit more to see the tail
    markets = fetch_top_volume_markets(limit=200) 
    analyze_volume_distribution(markets)
