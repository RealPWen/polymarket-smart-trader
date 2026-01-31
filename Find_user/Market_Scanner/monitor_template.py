import json
import websocket
import threading
import time
import sys
import os

# Ensure we can import scanner
sys.path.append(os.path.dirname(__file__))
from scanner import WhaleScanner

# Gamma WebSocket URL (Active data feed)
WS_URL = "wss://ws-gamma.polymarket.com/events" 
# Note: CLOB WS is better for Orderbook updates, Gamma WS is good for Trades/Markets.
# For "Trades" (Executions), Gamma WS /events with subscription is standard.

class RealTimeMonitor:
    def __init__(self, market_ids):
        self.market_ids = market_ids
        self.scanner = WhaleScanner({"min_usd_size": 1000}) # $1000 threshold for live
        self.ws = None
        
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            # Gamma WS messages vary. We look for 'trade' events.
            # Typical format: [{"type": "trade", "market": "...", ...}] or similar wrapped
             
            # Standard Gamma/CLOB trade message structure handling:
            event_type = data.get("event_type")
            
            if event_type == "trade":
                market_id = data.get("market")
                if market_id in self.market_ids:
                    # Construct pseudo market_info (we prioritize speed so maybe just ID)
                    market_info = {"id": market_id, "question": f"Market {market_id}"} 
                    
                    signal = self.scanner.process_trade(data, market_info)
                    if signal:
                        print(f"\n[ALERT] {signal['reason']} on {signal['market_id']}")
                        print(f"Details: {signal['side']} {signal['shares']} @ {signal['price']} (Wallet: {signal['wallet']})")
                        
        except Exception as e:
            # print(f"Error processing Msg: {e}")
            pass

    def on_error(self, ws, error):
        print(f"WS Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print("WS Closed")

    def on_open(self, ws):
        print("WS Open. Subscribing...")
        # Gamma WS requires standard subscription packet?
        # Actually Gamma WS is simple subscription.
        # Payload: {"assets": [ids...], "type": "market"} ? 
        # Check docs or assume simplified CLOB usage if needed.
        # For Gamma, usually just connecting gets stream or we filter?
        
        # If using CLOB WS:
        # msg = {"type": "Subscribe", "channels": [{"name": "trades", "market_ids": self.market_ids}]}
        # ws.send(json.dumps(msg))
        pass

    def start(self):
        # Using Common Clob WS for reliability if Gamma is tricky
        clob_url = "wss://ws.polymarket.com/ws/market"
        def on_open_clob(ws):
             print(f"Connected to CLOB. Subscribing to {len(self.market_ids)} markets...")
             msg = {
                 "type": "Subscribe", 
                 "channels": [
                     {"name": "trades", "token_ids": self.market_ids} 
                     # Note: CLOB uses Token IDs (Asset IDs) usually, not Market IDs (Condition IDs)?
                     # This is a critical distinction. 
                     # For 'Find Whale', we often have Market IDs (Integers or ConditionIDs).
                     # We need to resolve them to Asset IDs for CLOB WS.
                 ]
             }
             ws.send(json.dumps(msg))

        # This is a simplified template. 
        # Resolving IDs is complex without mapping.
        print("Note: Realtime Monitor requires Asset IDs (Token IDs).")
        print("For this demo, we rely on the Backtest first.")

if __name__ == "__main__":
    # Placeholder
    print("Run backtest.py first to identify strategy.")
