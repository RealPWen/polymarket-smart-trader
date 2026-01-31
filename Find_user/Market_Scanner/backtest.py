import os
import json
import statistics
from scanner import WhaleScanner

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def run_backtest():
    """
    Iterates through downloaded market data and runs the scanner.
    """
    print("Initializing Backtest...")
    
    # 1. Load Data
    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".json")]
    if not files:
        print("No data found. Please run fetch_data.py first.")
        return

    # Configuration for the Scanner
    scanner_config = {
        "min_usd_size": 2000 # Let's set a high bar, $2000
    }
    scanner = WhaleScanner(scanner_config)
    
    all_signals = []
    total_trades_scanned = 0
    
    print(f"Scanning {len(files)} markets...")
    print("-" * 60)
    print(f"{'Time':<20} {'Market':<30} {'Action':<10} {'Value':<10} {'Wallet'}")
    print("-" * 60)
    
    for fname in files:
        fpath = os.path.join(DATA_DIR, fname)
        with open(fpath, "r", encoding='utf-8') as f:
            data = json.load(f)
            
        market_info = data.get("market_info", {})
        trades = data.get("trades", [])
        
        # Sort trades by timestamp (oldest first) to simulate timeline
        # Timestamps are usually unix seconds (float) or iso strings? 
        # Gamma API returns numeric timestamps (seconds) usually.
        trades.sort(key=lambda x: x.get("timestamp", 0))
        
        for trade in trades:
            total_trades_scanned += 1
            signal = scanner.process_trade(trade, market_info)
            if signal:
                all_signals.append(signal)
                
                # Print formatted alert
                ts_str = str(signal['timestamp']) # Convert to readable detection
                short_q = signal['question'][:28] + ".."
                action = f"{signal['side']} @ {signal['price']:.2f}"
                val = f"${signal['burst_value']:,.0f}"
                wal = signal['wallet'][:6] + ".." if signal['wallet'] else "Unknown"
                
                print(f"{ts_str:<20} {short_q:<30} {action:<10} {val:<10} {wal}")

    print("-" * 60)
    print(f"Backtest Complete.")
    print(f"Total Trades Scanned: {total_trades_scanned}")
    print(f"Signals Triggered: {len(all_signals)}")
    
    # Summary Analysis (User wanted Validation)
    if all_signals:
        avg_val = statistics.mean([s['burst_value'] for s in all_signals])
        print(f"Average Signal Value: ${avg_val:,.2f}")
    
    # Save results
    with open("backtest_results.json", "w", encoding='utf-8') as f:
        json.dump(all_signals, f, indent=2)
        print("Results saved to backtest_results.json")

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    run_backtest()
