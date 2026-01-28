"""
Smart Follower Simulation

Simulates copy trading on filtered "smart money" wallets and calculates
advanced statistical metrics to validate their profitability.

Usage:
    # Single wallet simulation
    python smart_follower_sim.py --wallet 0x123...

    # Batch simulation from smart_wallets.json
    python smart_follower_sim.py --input output/smart_wallets_latest.json

    # Custom parameters
    python smart_follower_sim.py --input wallets.json --lookback 20 --slippage 100
"""

import argparse
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from scipy import stats

from sim_config import SimulationConfig, SimulationResult, DEFAULT_SIM_CONFIG
from polymarket_data_fetcher import PolymarketDataFetcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy types."""
    
    def default(self, obj):
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


class ClobPriceClient:
    """Client for fetching current market prices from CLOB API"""
    
    def __init__(self, base_url: str = "https://clob.polymarket.com"):
        self.base_url = base_url
        self.session = requests.Session()
        self._market_cache = {}  # Cache market data to reduce API calls
        
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
    
    def get_market(self, condition_id: str) -> Optional[Dict]:
        """
        Fetch market info by conditionId.
        Returns market data including tokens with current prices.
        """
        # Check cache first
        if condition_id in self._market_cache:
            return self._market_cache[condition_id]
        
        url = f"{self.base_url}/markets/{condition_id}"
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            market = response.json()
            self._market_cache[condition_id] = market
            return market
        except Exception as e:
            logger.debug(f"Failed to fetch market {condition_id[:16]}...: {e}")
            return None
    
    def get_token_current_price(self, condition_id: str, token_id: str) -> Optional[Dict]:
        """
        Get the current price and winner status for a specific token.
        
        Args:
            condition_id: The market's conditionId
            token_id: The token's asset ID
        
        Returns:
            Dict with 'price', 'winner', 'outcome', or None if not found.
        """
        market = self.get_market(condition_id)
        
        if not market:
            return None
        
        tokens = market.get("tokens", [])
        
        for token in tokens:
            if token.get("token_id") == token_id:
                return {
                    "price": float(token.get("price", 0)),
                    "winner": token.get("winner", False),
                    "outcome": token.get("outcome", "Unknown"),
                    "market_closed": market.get("closed", False),
                }
        
        return None
    
    def clear_cache(self):
        """Clear the market cache."""
        self._market_cache = {}


class SmartFollowerSimulator:
    """
    Simulates copy trading on smart money wallets.
    
    For each wallet:
    1. Fetch recent BUY trades
    2. Calculate simulated entry price (with slippage)
    3. Get current exit price from CLOB order book
    4. Calculate PnL and statistical metrics
    """
    
    def __init__(self, config: Optional[SimulationConfig] = None):
        self.config = config or DEFAULT_SIM_CONFIG
        self.fetcher = PolymarketDataFetcher()
        self.clob_client = ClobPriceClient(self.config.clob_api_base)
    
    def fetch_recent_trades(self, wallet_address: str, limit: int = None) -> List[Dict]:
        """
        Fetch recent trades for a wallet.
        
        Args:
            wallet_address: The wallet to fetch trades for.
            limit: Maximum number of trades to fetch.
        
        Returns:
            List of trade dictionaries.
        """
        limit = limit or self.config.lookback_count
        
        df = self.fetcher.get_trades(
            wallet_address=wallet_address,
            limit=limit,
            silent=True
        )
        
        if df.empty:
            return []
        
        # Convert to list of dicts
        trades = df.to_dict('records')
        
        # Filter to BUY trades only (we simulate following their buys)
        buy_trades = [t for t in trades if t.get('side', '').upper() == 'BUY']
        
        return buy_trades
    
    def simulate_single_trade(self, trade: Dict) -> Optional[Dict]:
        """
        Simulate following a single trade.
        
        Simplified logic:
        1. Use trader's entry price
        2. Use trader's shares (size)
        3. Get current market price from CLOB API
        4. PnL = (current_price - entry_price) * shares
        
        Args:
            trade: Trade dictionary from the API.
        
        Returns:
            Dict with simulation results, or None if price unavailable.
        """
        # Extract trade info
        asset_id = str(trade.get('asset', ''))  # token_id
        condition_id = str(trade.get('conditionId', ''))
        entry_price = float(trade.get('price', 0))
        shares = float(trade.get('size', 0))
        
        if not asset_id or not condition_id or entry_price <= 0 or shares <= 0:
            return None
        
        # Apply slippage to entry price (we would have paid slightly more)
        slippage_multiplier = 1 + (self.config.slippage_bps / 10000)
        simulated_entry_price = entry_price * slippage_multiplier
        
        # Get current price from CLOB market API
        token_info = self.clob_client.get_token_current_price(condition_id, asset_id)
        
        if token_info is None:
            return None
        
        current_price = token_info["price"]
        is_winner = token_info["winner"]
        market_closed = token_info["market_closed"]
        outcome = token_info["outcome"]
        
        # For closed markets where winner is determined:
        # - Winner token = 1.0 (redeemable for $1)
        # - Loser token = 0.0 (worthless)
        if market_closed and is_winner is not None:
            if is_winner:
                current_price = 1.0
            elif is_winner is False:
                current_price = 0.0
        
        # Calculate PnL
        # Cost = entry_price * shares (with slippage)
        # Value = current_price * shares
        cost = simulated_entry_price * shares
        value = current_price * shares
        absolute_pnl = value - cost
        pnl_percent = (current_price - simulated_entry_price) / simulated_entry_price if simulated_entry_price > 0 else 0
        
        return {
            "asset_id": asset_id,
            "condition_id": condition_id,
            "outcome": outcome,
            "entry_price": entry_price,
            "simulated_entry_price": simulated_entry_price,
            "current_price": current_price,
            "shares": shares,
            "cost": cost,
            "value": value,
            "absolute_pnl": absolute_pnl,
            "pnl_percent": pnl_percent,
            "market_closed": market_closed,
            "is_winner": is_winner,
        }
    
    def calculate_statistics(self, pnl_list: List[float]) -> Dict[str, float]:
        """
        Calculate advanced statistical metrics from PnL list.
        
        Args:
            pnl_list: List of PnL percentages per trade.
        
        Returns:
            Dict with sharpe_ratio, sortino_ratio, max_drawdown, pvalue, kelly_fraction.
        """
        if len(pnl_list) < self.config.min_trades_for_stats:
            return {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "max_drawdown": 0.0,
                "pvalue": 1.0,
                "kelly_fraction": 0.0,
            }
        
        returns = np.array(pnl_list)
        
        # Sharpe Ratio
        # Normalized by sqrt(n) as a proxy for annualization
        std_returns = np.std(returns)
        if std_returns > 0:
            sharpe = (np.mean(returns) - self.config.risk_free_rate) / std_returns * np.sqrt(len(returns))
        else:
            sharpe = 0.0
        
        # Sortino Ratio (only downside deviation)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0:
            downside_std = np.std(downside_returns)
            if downside_std > 0:
                sortino = (np.mean(returns) - self.config.risk_free_rate) / downside_std * np.sqrt(len(returns))
            else:
                sortino = float('inf') if np.mean(returns) > 0 else 0.0
        else:
            # No negative returns
            sortino = float('inf') if np.mean(returns) > 0 else 0.0
        
        # Cap sortino at a reasonable value for display
        sortino = min(sortino, 100.0)
        
        # Max Drawdown
        cumulative = np.cumsum(returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = running_max - cumulative
        max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0.0
        
        # P-Value (one-sample t-test, H0: mean <= 0)
        if len(returns) >= 2 and std_returns > 0:
            t_stat, p_two_tailed = stats.ttest_1samp(returns, 0)
            # One-tailed: we only care if mean > 0
            p_value = p_two_tailed / 2 if t_stat > 0 else 1 - p_two_tailed / 2
        else:
            p_value = 1.0
        
        # Kelly Criterion
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        
        if len(wins) > 0 and len(losses) > 0:
            win_rate = len(wins) / len(returns)
            avg_win = np.mean(wins)
            avg_loss = abs(np.mean(losses))
            
            if avg_loss > 0:
                b = avg_win / avg_loss  # Win/loss ratio
                kelly = (b * win_rate - (1 - win_rate)) / b
            else:
                kelly = win_rate  # All wins, no losses
        elif len(wins) > 0:
            kelly = 1.0  # All wins
        else:
            kelly = 0.0  # No wins
        
        # Clamp kelly to reasonable range
        kelly = max(0.0, min(kelly, 1.0))
        
        return {
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": round(sortino, 4),
            "max_drawdown": round(max_drawdown, 4),
            "pvalue": round(p_value, 6),
            "kelly_fraction": round(kelly, 4),
        }
    
    def run_simulation(self, wallet_address: str) -> SimulationResult:
        """
        Run full mirror trading simulation for a single wallet.
        
        Logic:
        1. Fetch recent trades (BUY and SELL).
        2. Replay trades in chronological order.
        3. Track 'virtual portfolio' (position size, average entry price).
        4. On SELL: Calculate Realized PnL based on avg entry price.
        5. At end: Calculate Unrealized PnL for remaining positions using current market prices/settlement.
        
        Args:
            wallet_address: The wallet to simulate.
        
        Returns:
            SimulationResult with all metrics.
        """
        result = SimulationResult(wallet_address=wallet_address)
        
        try:
            # 1. Fetch recent trades (limit increased to ensure we capture open/close cycles)
            # Fetch more trades to increase chance of finding the entry for a sale
            fetch_limit = self.config.lookback_count * 2 
            df = self.fetcher.get_trades(
                wallet_address=wallet_address,
                limit=fetch_limit,
                silent=True
            )
            
            if df.empty:
                result.error_message = "No trades found"
                return result
            
            # Sort by timestamp ascending (oldest first) to replay history
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_numeric(df['timestamp'])
                df = df.sort_values('timestamp', ascending=True)
            else:
                # Fallback: assume API returns newest first, so reverse it
                df = df.iloc[::-1]
            
            trades = df.to_dict('records')
            result.trades_simulated = len(trades)
            
            # 2. Replay history
            # Portfolio state: asset_id -> { 'size': float, 'cost_basis': float, 'avg_price': float }
            portfolio = {} 
            closed_pnl_records = [] # List of realized PnL info
            
            slippage_bps = self.config.slippage_bps / 10000
            
            for trade in trades:
                asset_id = str(trade.get('asset', ''))
                side = trade.get('side', '').upper()
                price = float(trade.get('price', 0))
                size = float(trade.get('size', 0))
                condition_id = str(trade.get('conditionId', ''))
                
                if not asset_id or price <= 0 or size <= 0:
                    continue
                
                # Initialize position if new
                if asset_id not in portfolio:
                    portfolio[asset_id] = {'size': 0.0, 'cost_basis': 0.0, 'avg_price': 0.0, 'condition_id': condition_id}
                
                position = portfolio[asset_id]
                
                if side == 'BUY':
                    # Apply slippage: We buy slightly higher
                    sim_buy_price = price * (1 + slippage_bps)
                    cost = sim_buy_price * size
                    
                    # Update weighted average price
                    new_size = position['size'] + size
                    new_cost_basis = position['cost_basis'] + cost
                    
                    position['size'] = new_size
                    position['cost_basis'] = new_cost_basis
                    if new_size > 0:
                        position['avg_price'] = new_cost_basis / new_size
                        
                elif side == 'SELL':
                    # Check if we have inventory to sell
                    # If we don't have inventory (e.g. bought before our lookback window), 
                    # we ignore this sell or assume 0 cost? 
                    # Better to ignore to avoid skewing stats with 100% profit.
                    if position['size'] <= 0.0001:
                        continue
                        
                    # Determine how much we can sell
                    sell_size = min(size, position['size'])
                    
                    # Apply slippage: We sell slightly lower
                    sim_sell_price = price * (1 - slippage_bps)
                    
                    # Calculate Realized PnL
                    # Profit = (Sell Price - Avg Buy Price) * Size
                    avg_entry_price = position['avg_price']
                    trade_pnl_abs = (sim_sell_price - avg_entry_price) * sell_size
                    trade_pnl_pct = (sim_sell_price - avg_entry_price) / avg_entry_price if avg_entry_price > 0 else 0
                    
                    closed_pnl_records.append({
                        'type': 'REALIZED',
                        'asset_id': asset_id,
                        'pnl_abs': trade_pnl_abs,
                        'pnl_pct': trade_pnl_pct,
                        'size': sell_size,
                        'entry_price': avg_entry_price,
                        'exit_price': sim_sell_price
                    })
                    
                    # Update position (reduce size and cost basis proportionally)
                    pct_sold = sell_size / position['size']
                    position['size'] -= sell_size
                    position['cost_basis'] *= (1 - pct_sold)
                    # avg_price remains the same
            
            # 3. Calculate Unrealized PnL for remaining positions
            trades_with_price = len(closed_pnl_records) # Start count with realized trades
            
            for asset_id, position in portfolio.items():
                remaining_size = position['size']
                if remaining_size <= 0.0001:
                    continue
                
                # Skip dust positions (cost basis < min_position_value)
                cost_basis = position.get('cost_basis', 0)
                if cost_basis < self.config.min_position_value:
                    continue
                
                # Fetch current market price
                condition_id = position.get('condition_id')
                if not condition_id:
                    continue
                    
                token_info = self.clob_client.get_token_current_price(condition_id, asset_id)
                
                if not token_info:
                    continue
                
                current_price = token_info["price"]
                market_closed = token_info["market_closed"]
                is_winner = token_info["winner"]
                
                # Handle Settlement
                if market_closed and is_winner is not None:
                    current_price = 1.0 if is_winner else 0.0
                
                # Calculate Unrealized PnL
                avg_entry_price = position['avg_price']
                current_val = current_price * remaining_size
                cost_basis = position['cost_basis'] # Or avg_entry_price * remaining_size
                
                # Adjust cost basis for remaining size if needed (it should match)
                cost_basis = avg_entry_price * remaining_size
                
                pnl_abs = current_val - cost_basis
                pnl_pct = (current_price - avg_entry_price) / avg_entry_price if avg_entry_price > 0 else 0
                
                closed_pnl_records.append({
                    'type': 'UNREALIZED',
                    'asset_id': asset_id,
                    'pnl_abs': pnl_abs,
                    'pnl_pct': pnl_pct,
                    'size': remaining_size,
                    'entry_price': avg_entry_price,
                    'exit_price': current_price,
                    'market_status': 'CLOSED' if market_closed else 'OPEN'
                })
                trades_with_price += 1
                
                # Rate limit for loop
                time.sleep(self.config.request_delay_seconds)

            # 4. Compile Results
            if not closed_pnl_records:
                result.error_message = "No closed trades or open positions with price found"
                return result
                
            pnl_pct_list = [r['pnl_pct'] for r in closed_pnl_records]
            pnl_abs_list = [r['pnl_abs'] for r in closed_pnl_records]
            
            result.trades_with_price = trades_with_price
            result.pnl_list = pnl_pct_list
            
            # Metrics
            result.total_simulated_pnl = sum(pnl_abs_list)
            
            # Approximate total capital deployed (sum of all entry costs)
            # This is a simplification for ROI calc
            total_invested = sum([r['entry_price'] * r['size'] for r in closed_pnl_records])
            
            if total_invested > 0:
                result.simulated_roi_percent = (result.total_simulated_pnl / total_invested) * 100
            else:
                result.simulated_roi_percent = 0.0
                
            result.simulated_win_rate = len([p for p in pnl_pct_list if p > 0]) / len(pnl_pct_list)
            
            # Advanced Stats
            stats_result = self.calculate_statistics(pnl_pct_list)
            result.sharpe_ratio = stats_result["sharpe_ratio"]
            result.sortino_ratio = stats_result["sortino_ratio"]
            result.max_drawdown = stats_result["max_drawdown"]
            result.pvalue = stats_result["pvalue"]
            result.kelly_fraction = stats_result["kelly_fraction"]
            
            # Risk Flags
            result.high_drawdown_risk = result.max_drawdown > self.config.max_acceptable_drawdown
            result.statistically_significant = result.pvalue < self.config.max_acceptable_pvalue
            
        except Exception as e:
            result.error_message = str(e)
            logger.error(f"Simulation failed for {wallet_address[:16]}...: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return result
    
    def run_batch(self, wallets: List[str], max_workers: int = None) -> List[SimulationResult]:
        """
        Run simulation for multiple wallets in parallel.
        
        Args:
            wallets: List of wallet addresses.
            max_workers: Number of parallel workers.
        
        Returns:
            List of SimulationResult objects.
        """
        max_workers = max_workers or self.config.max_workers
        results = []
        
        logger.info(f"Starting batch simulation for {len(wallets)} wallets (workers={max_workers})")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_wallet = {
                executor.submit(self.run_simulation, wallet): wallet 
                for wallet in wallets
            }
            
            for i, future in enumerate(as_completed(future_to_wallet)):
                wallet = future_to_wallet[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    # Progress logging
                    processed_count = i + 1
                    logger.info(f"Progress: {processed_count}/{len(wallets)} wallets processed ({(processed_count/len(wallets)*100):.1f}%)")
                    
                    # Incremental save (simple append to CSV)
                    temp_csv = os.path.join(self.config.output_dir, "simulation_temp_progress.csv")
                    is_new_file = not os.path.exists(temp_csv)
                    
                    df_res = pd.DataFrame([asdict(result)])
                    # Exclude 'pnl_list' from CSV as it's too large/complex for flat CSV
                    if 'pnl_list' in df_res.columns:
                        df_res = df_res.drop(columns=['pnl_list'])
                    
                    df_res.to_csv(temp_csv, mode='a', header=is_new_file, index=False, encoding='utf-8-sig')
                    
                except Exception as e:
                    logger.error(f"Failed to process {wallet[:16]}...: {e}")
                    results.append(SimulationResult(
                        wallet_address=wallet,
                        error_message=str(e)
                    ))
        
        return results
    
    def save_results(self, results: List[SimulationResult], prefix: str = "simulation") -> str:
        """
        Save simulation results to CSV and JSON.
        
        Args:
            results: List of SimulationResult objects.
            prefix: Filename prefix.
        
        Returns:
            Path to the saved CSV file.
        """
        # Ensure output directory exists
        os.makedirs(self.config.output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Convert to DataFrame
        records = []
        for r in results:
            record = asdict(r)
            # Remove large pnl_list from CSV output
            record.pop('pnl_list', None)
            records.append(record)
        
        df = pd.DataFrame(records)
        
        # Sort by simulated ROI
        if 'simulated_roi_percent' in df.columns:
            df = df.sort_values('simulated_roi_percent', ascending=False)
        
        # Save CSV
        csv_path = os.path.join(self.config.output_dir, f"{prefix}_{timestamp}.csv")
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        logger.info(f"Saved CSV results to: {csv_path}")
        
        # Save JSON with full data
        if self.config.save_json:
            json_path = os.path.join(self.config.output_dir, f"{prefix}_{timestamp}.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump([asdict(r) for r in results], f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
            logger.info(f"Saved JSON results to: {json_path}")
        
        return csv_path
    
    def print_summary(self, results: List[SimulationResult]):
        """Print a summary of simulation results."""
        if not results:
            logger.warning("No results to summarize")
            return
        
        valid_results = [r for r in results if r.trades_with_price > 0]
        
        print("\n" + "=" * 60)
        print("SIMULATION SUMMARY")
        print("=" * 60)
        print(f"Total wallets processed: {len(results)}")
        print(f"Wallets with valid data: {len(valid_results)}")
        
        if valid_results:
            avg_roi = np.mean([r.simulated_roi_percent for r in valid_results])
            avg_win_rate = np.mean([r.simulated_win_rate for r in valid_results])
            avg_sharpe = np.mean([r.sharpe_ratio for r in valid_results])
            significant_count = sum(1 for r in valid_results if r.statistically_significant)
            
            print(f"\nAverage Simulated ROI: {avg_roi:.2f}%")
            print(f"Average Win Rate: {avg_win_rate*100:.1f}%")
            print(f"Average Sharpe Ratio: {avg_sharpe:.2f}")
            print(f"Statistically Significant (p<0.10): {significant_count}/{len(valid_results)}")
            
            # Top performers
            top_5 = sorted(valid_results, key=lambda x: x.simulated_roi_percent, reverse=True)[:5]
            print("\nTop 5 Performers:")
            for i, r in enumerate(top_5, 1):
                sig_marker = "*" if r.statistically_significant else ""
                print(f"  {i}. {r.wallet_address[:16]}... ROI: {r.simulated_roi_percent:.2f}% "
                      f"WR: {r.simulated_win_rate*100:.0f}% Sharpe: {r.sharpe_ratio:.2f}{sig_marker}")
        
        print("=" * 60 + "\n")


def load_wallets_from_file(file_path: str) -> List[str]:
    """Load wallet addresses from JSON or CSV file."""
    if file_path.endswith('.json'):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                # Could be list of strings or list of dicts
                if data and isinstance(data[0], str):
                    return data
                elif data and isinstance(data[0], dict):
                    return [d.get('wallet_address', d.get('address', '')) for d in data if d]
    elif file_path.endswith('.csv'):
        df = pd.read_csv(file_path)
        # Try common column names
        for col in ['wallet_address', 'address', 'proxyWallet', 'wallet']:
            if col in df.columns:
                return df[col].dropna().tolist()
    
    raise ValueError(f"Could not parse wallet addresses from {file_path}")


def find_latest_smart_wallets() -> Optional[str]:
    """Find the latest smart_wallets JSON file in output directory."""
    output_dir = "output"
    if not os.path.exists(output_dir):
        return None
    
    files = [f for f in os.listdir(output_dir) if f.startswith('smart_wallets') and f.endswith('.json')]
    
    if not files:
        return None
    
    # Sort by modification time
    files.sort(key=lambda x: os.path.getmtime(os.path.join(output_dir, x)), reverse=True)
    return os.path.join(output_dir, files[0])


def main():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Smart Follower Simulation - Backtest copy trading on smart money wallets"
    )
    
    # Input options
    parser.add_argument(
        "--wallet", "-w",
        type=str,
        help="Single wallet address to simulate"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        help="Path to JSON/CSV file with wallet addresses"
    )
    
    # Simulation parameters
    parser.add_argument(
        "--lookback", "-l",
        type=int,
        default=10,
        help="Number of recent trades to analyze (default: 10)"
    )
    parser.add_argument(
        "--slippage",
        type=int,
        default=50,
        help="Slippage in basis points (default: 50 = 0.5%%)"
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=100.0,
        help="Simulated USDC per trade (default: 100)"
    )
    
    # Processing options
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of parallel workers (default: 5)"
    )
    
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="Randomly sample N wallets (default: 0 = all)"
    )
    
    args = parser.parse_args()
    
    # Build configuration
    config = SimulationConfig(
        lookback_count=args.lookback,
        slippage_bps=args.slippage,
        sim_amount_per_trade=args.amount,
        max_workers=args.workers,
    )
    
    # Initialize simulator
    simulator = SmartFollowerSimulator(config)
    
    # Determine wallets to process
    wallets = []
    
    if args.wallet:
        wallets = [args.wallet]
    elif args.input:
        wallets = load_wallets_from_file(args.input)
    else:
        # Try to find latest smart_wallets file
        latest_file = find_latest_smart_wallets()
        if latest_file:
            logger.info(f"Using latest smart wallets file: {latest_file}")
            wallets = load_wallets_from_file(latest_file)
        else:
            parser.error("No input provided. Use --wallet or --input, or run smart_trader_analyzer.py first.")
    
    if not wallets:
        logger.error("No wallets to process")
        return
    
    # Random sampling
    if args.sample > 0 and len(wallets) > args.sample:
        import random
        random.shuffle(wallets)
        original_count = len(wallets)
        wallets = wallets[:args.sample]
        logger.info(f"Sampled {len(wallets)} wallets from total {original_count}")
    
    logger.info(f"Loaded {len(wallets)} wallets for simulation")
    
    # Run simulation
    if len(wallets) == 1:
        result = simulator.run_simulation(wallets[0])
        results = [result]
    else:
        results = simulator.run_batch(wallets, max_workers=config.max_workers)
    
    # Save and display results
    simulator.save_results(results)
    simulator.print_summary(results)


if __name__ == "__main__":
    main()
