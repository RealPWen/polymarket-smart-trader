from datetime import datetime
from collections import defaultdict

class WhaleScanner:
    def __init__(self, config=None):
        self.config = config or {}
        # Threshold for "Whale" (Single Trade or Aggregated Burst)
        self.min_usd_size = self.config.get("min_usd_size", 2000) 
        self.burst_window_seconds = self.config.get("burst_window", 10)
        # Max price to consider as "directional bet" (not buying No at 0.99)
        self.max_entry_price = self.config.get("max_entry_price", 0.80)
        
        # Buffer to track recent trades for burst detection
        # Format: {wallet_address: [list of trade_events]}
        self.recent_activity = defaultdict(list)
        
    def process_trade(self, trade, market_info):
        """
        Analyzes a single trade event.
        Returns a 'Signal' object or None.
        """
        try:
            timestamp = float(trade.get("timestamp", 0))
            # Data API provides 'proxyWallet' which is the user involved in this trade record
            # In Data API, each record is from the perspective of the user in 'proxyWallet'? 
            # Or is it a public tape?
            # Public tape usually doesn't delineate 'proxyWallet' unless it is the Taker?
            # Let's assume proxyWallet is the aggressor for now or the primary actor.
            aggressor = trade.get("proxyWallet") or trade.get("taker_address")
            
            maker = trade.get("maker_address") # Might be None
            
            size_shares = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            usd_value = size_shares * price
            
            # Identify the aggressor (Taker)
            if not aggressor:
                return None
                
            side = trade.get("side", "buy").upper() # Side of the trade relative to proxyWallet
            
            # --- Burst Detection Logic ---
            # 1. Add current trade to wallet's history buffer
            current_event = {
                "timestamp": timestamp,
                "usd_value": usd_value,
                "side": side,
                "price": price,
                "market_id": market_info.get("id")
            }
            self.recent_activity[aggressor].append(current_event)
            
            # 2. Prune old trades (> window sec ago)
            cutoff_time = timestamp - self.burst_window_seconds
            self.recent_activity[aggressor] = [
                t for t in self.recent_activity[aggressor] 
                if t['timestamp'] >= cutoff_time and t['market_id'] == market_info.get("id")
            ]
            
            # 3. Calculate Aggregated Stats for this Window
            window_trades = self.recent_activity[aggressor]
            total_buy_val = sum(t['usd_value'] for t in window_trades if t['side'] == 'BUY')
            total_sell_val = sum(t['usd_value'] for t in window_trades if t['side'] == 'SELL')
            
            net_flow = total_buy_val - total_sell_val
            abs_flow = abs(net_flow)
            
            # --- Filter: Only care about BUY at low prices ---
            # High price buys (e.g., 0.99) are usually buying "No" = not a directional bet
            # We only want low price buys (e.g., < 0.80) which represent real conviction
            
            # Check if this is a significant BUY burst at a reasonable entry price
            if total_buy_val > self.min_usd_size and price <= self.max_entry_price:
                return {
                    "type": "WHALE_BUY",
                    "timestamp": timestamp,
                    "market_id": market_info.get("id"),
                    "question": market_info.get("question"),
                    "outcome": trade.get("outcome", "Yes"), # Which outcome they bought
                    "side": "BUY",
                    "price": price, # latest price
                    "burst_value": total_buy_val, # Total BUY value in window
                    "wallet": aggressor,
                    "reason": f"Large BUY ${total_buy_val:,.0f} @ {price:.2f} in {self.burst_window_seconds}s"
                }
            
            return None
            
        except Exception as e:
            # print(f"Error parsing trade: {e}")
            return None
