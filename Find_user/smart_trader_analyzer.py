"""
Smart Trader Analyzer

Analyzes and filters traders from leaderboard data to identify "smart money".
Calculates advanced metrics including win rate, ROI, position concentration, etc.

Usage:
    python smart_trader_analyzer.py                          # Analyze latest leaderboard
    python smart_trader_analyzer.py --input data.csv         # Analyze specific file
    python smart_trader_analyzer.py --min-pnl 20000          # Custom PnL filter
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import numpy as np
import json
import time
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from dataclasses import dataclass, asdict

from discovery_config import (
    DiscoveryConfig,
    FilterConfig,
    AnalysisConfig,
    DEFAULT_CONFIG,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class TraderMetrics:
    """Calculated metrics for a trader"""
    wallet_address: str
    
    # Basic stats from leaderboard
    pnl: float = 0.0
    volume: float = 0.0
    rank: int = 0
    
    # Calculated metrics
    roi_percent: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    # Position metrics
    open_positions: int = 0
    closed_positions: int = 0
    avg_position_size: float = 0.0
    max_position_size: float = 0.0
    
    # Risk metrics
    position_concentration: float = 0.0
    avg_realized_pnl: float = 0.0
    unrealized_pnl_sum: float = 0.0
    
    # Activity metrics
    last_trade_timestamp: int = 0
    last_trade_date: Optional[str] = None
    
    # Profile info
    username: Optional[str] = None
    is_verified: bool = False
    is_market_maker: bool = False
    
    # Analysis flags
    meets_criteria: bool = False
    filter_reason: Optional[str] = None


class SmartTraderAnalyzer:
    """Analyzes traders to identify smart money candidates"""
    
    DATA_API_URL = "https://data-api.polymarket.com"
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, config: Optional[DiscoveryConfig] = None):
        self.config = config or DEFAULT_CONFIG
        self.filter_config = self.config.filter
        self.analysis_config = self.config.analysis
        self.session = self._create_session()
        self._metrics_cache: Dict[str, TraderMetrics] = {}
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session
    
    def load_leaderboard_data(self, file_path: Optional[str] = None) -> pd.DataFrame:
        """Load leaderboard data from file or find latest"""
        if file_path:
            if file_path.endswith(".csv"):
                df = pd.read_csv(file_path)
            elif file_path.endswith(".json"):
                df = pd.read_json(file_path)
            else:
                raise ValueError(f"Unsupported file format: {file_path}")
            logger.info(f"Loaded {len(df)} traders from {file_path}")
            return df
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, self.config.output.output_dir)
        
        if os.path.exists(output_dir):
            csv_files = [f for f in os.listdir(output_dir) if f.startswith("leaderboard") and f.endswith(".csv")]
            if csv_files:
                latest_file = sorted(csv_files)[-1]
                file_path = os.path.join(output_dir, latest_file)
                df = pd.read_csv(file_path)
                logger.info(f"Loaded {len(df)} traders from {file_path}")
                return df
        
        logger.warning("No leaderboard data found. Please run fetch_leaderboard.py first.")
        return pd.DataFrame()
    
    def apply_basic_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply basic filters based on PnL and volume thresholds"""
        original_count = len(df)
        
        if self.filter_config.min_pnl:
            df = df[df["pnl"] >= self.filter_config.min_pnl]
            logger.info(f"After min PnL filter (${self.filter_config.min_pnl:,.0f}): {len(df)} traders")
        
        if self.filter_config.max_pnl:
            df = df[df["pnl"] <= self.filter_config.max_pnl]
        
        if self.filter_config.min_volume:
            df = df[df["vol"] >= self.filter_config.min_volume]
            logger.info(f"After min volume filter (${self.filter_config.min_volume:,.0f}): {len(df)} traders")
        
        if "pnl" in df.columns and "vol" in df.columns:
            df = df.copy()
            df["roi_percent"] = (df["pnl"] / df["vol"]) * 100
            
            if self.filter_config.min_roi_percent:
                df = df[df["roi_percent"] >= self.filter_config.min_roi_percent]
            
            if self.filter_config.max_roi_percent:
                df = df[df["roi_percent"] <= self.filter_config.max_roi_percent]
                logger.info(f"After ROI filters: {len(df)} traders")
        
        if self.filter_config.exclude_market_makers:
            mm_addresses = set(self.filter_config.market_maker_addresses)
            if mm_addresses:
                df = df[~df["proxyWallet"].isin(mm_addresses)]
                logger.info(f"After market maker filter: {len(df)} traders")
        
        logger.info(f"Basic filters: {original_count} -> {len(df)} traders")
        return df
    
    def fetch_closed_positions(self, wallet_address: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch closed positions for a wallet, sorted by time DESC"""
        positions = []
        offset = 0
        
        while len(positions) < limit:
            url = f"{self.DATA_API_URL}/v1/closed-positions"
            params = {
                "user": wallet_address,
                "limit": min(50, limit - len(positions)),
                "offset": offset,
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC",
            }
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                if not data:
                    break
                positions.extend(data)
                offset += len(data)
                if len(data) < 50:
                    break
                time.sleep(0.2)
            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching closed positions for {wallet_address}: {e}")
                break
        return positions
    
    def fetch_current_positions(self, wallet_address: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch current (open) positions for a wallet"""
        url = f"{self.DATA_API_URL}/positions"
        params = {
            "user": wallet_address,
            "limit": min(limit, 500),
            "sizeThreshold": 1,
        }
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching current positions for {wallet_address}: {e}")
            return []
    
    def calculate_metrics(self, wallet_address: str, leaderboard_data: Dict[str, Any]) -> TraderMetrics:
        """Calculate detailed metrics for a trader"""
        metrics = TraderMetrics(
            wallet_address=wallet_address,
            pnl=leaderboard_data.get("pnl", 0),
            volume=leaderboard_data.get("vol", 0),
            rank=int(leaderboard_data.get("rank", 0)),
            username=leaderboard_data.get("userName"),
            is_verified=leaderboard_data.get("verifiedBadge", False),
        )
        
        if metrics.volume > 0:
            metrics.roi_percent = (metrics.pnl / metrics.volume) * 100
        
        closed_positions = self.fetch_closed_positions(wallet_address, limit=self.analysis_config.max_positions_to_fetch)
        current_positions = self.fetch_current_positions(wallet_address)
        
        metrics.closed_positions = len(closed_positions)
        metrics.open_positions = len(current_positions)

        # Activity Check - get last trade timestamp
        if closed_positions:
            last_ts = closed_positions[0].get("timestamp", 0)
            metrics.last_trade_timestamp = last_ts
            if last_ts > 0:
                metrics.last_trade_date = datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d %H:%M:%S')

        # Win Rate Calculation (Closed + Open)
        winning_count = 0
        losing_count = 0
        
        if closed_positions:
            for p in closed_positions:
                if p.get("realizedPnl", 0) > 0:
                    winning_count += 1
                else:
                    losing_count += 1
            total_realized = sum(p.get("realizedPnl", 0) for p in closed_positions)
            metrics.avg_realized_pnl = total_realized / len(closed_positions)

        unrealized_pnl_sum = 0.0
        if current_positions:
            for p in current_positions:
                pnl = p.get("cashPnl", 0)
                unrealized_pnl_sum += pnl
                if pnl > 0:
                    winning_count += 1
                else:
                    losing_count += 1
            
            metrics.unrealized_pnl_sum = unrealized_pnl_sum
            values = [abs(p.get("currentValue", 0)) for p in current_positions]
            total_value = sum(values)
            if total_value > 0:
                metrics.max_position_size = max(values)
                metrics.avg_position_size = total_value / len(values)
                metrics.position_concentration = max(values) / total_value

        metrics.winning_trades = winning_count
        metrics.losing_trades = losing_count
        metrics.total_trades = winning_count + losing_count
        
        if metrics.total_trades > 0:
            metrics.win_rate = winning_count / metrics.total_trades
        
        metrics.meets_criteria = self._check_criteria(metrics)
        return metrics
    
    def _check_criteria(self, metrics: TraderMetrics) -> bool:
        """Check if a trader meets all criteria"""
        reasons = []
        
        # Check inactivity
        if metrics.last_trade_timestamp > 0:
            last_trade_dt = datetime.fromtimestamp(metrics.last_trade_timestamp)
            days_since = (datetime.now() - last_trade_dt).days
            if days_since > self.filter_config.max_inactivity_days:
                reasons.append(f"Inactive for {days_since} days (> {self.filter_config.max_inactivity_days})")
        elif metrics.closed_positions == 0:
            reasons.append("No closed positions found (Inactive)")

        # Check minimum closed positions
        if metrics.closed_positions < self.analysis_config.min_closed_positions:
            reasons.append(f"Closed positions ({metrics.closed_positions}) < {self.analysis_config.min_closed_positions}")
        
        # Check win rate
        if metrics.total_trades > 0:
            if metrics.win_rate < self.analysis_config.min_win_rate:
                reasons.append(f"Win rate ({metrics.win_rate:.1%}) < {self.analysis_config.min_win_rate:.1%}")
        
        # Check position concentration
        if metrics.position_concentration > self.analysis_config.max_concentration:
            reasons.append(f"Concentration ({metrics.position_concentration:.1%}) > {self.analysis_config.max_concentration:.1%}")
        
        if reasons:
            metrics.filter_reason = "; ".join(reasons)
            return False
        
        return True
    
    def analyze_candidates(self, df: pd.DataFrame, max_workers: int = None) -> List[TraderMetrics]:
        """Analyze all candidate traders in parallel"""
        max_workers = max_workers or self.analysis_config.max_workers
        candidates = df.to_dict("records")
        results = []
        
        logger.info(f"Analyzing {len(candidates)} candidates with {max_workers} workers")
        
        def analyze_one(record: Dict) -> TraderMetrics:
            wallet = record.get("proxyWallet")
            time.sleep(0.3)
            return self.calculate_metrics(wallet, record)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(analyze_one, record): record for record in candidates}
            
            for future in tqdm(as_completed(futures), total=len(futures), desc="Analyzing"):
                try:
                    metrics = future.result()
                    results.append(metrics)
                    self._metrics_cache[metrics.wallet_address] = metrics
                except Exception as e:
                    record = futures[future]
                    logger.error(f"Error analyzing {record.get('proxyWallet')}: {e}")
        
        return results
    
    def filter_smart_traders(self, metrics_list: List[TraderMetrics]) -> List[TraderMetrics]:
        """Filter metrics to get final smart trader list"""
        smart_traders = [m for m in metrics_list if m.meets_criteria]
        smart_traders.sort(key=lambda x: x.pnl, reverse=True)
        logger.info(f"Smart traders identified: {len(smart_traders)} / {len(metrics_list)}")
        return smart_traders
    
    def to_dataframe(self, metrics_list: List[TraderMetrics]) -> pd.DataFrame:
        """Convert metrics list to DataFrame"""
        return pd.DataFrame([asdict(m) for m in metrics_list])
    
    def save_results(self, smart_traders: List[TraderMetrics], all_metrics: List[TraderMetrics], prefix: str = "smart_traders") -> Dict[str, str]:
        """Save analysis results to files"""
        output_config = self.config.output
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, output_config.output_dir)
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime(output_config.timestamp_format)
        saved_files = {}
        
        smart_df = self.to_dataframe(smart_traders)
        
        if output_config.save_csv:
            csv_path = os.path.join(output_dir, f"{prefix}_{timestamp}.csv")
            smart_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            saved_files["smart_csv"] = csv_path
        
        if output_config.save_json:
            json_path = os.path.join(output_dir, f"{prefix}_{timestamp}.json")
            smart_df.to_json(json_path, orient="records", indent=2, force_ascii=False)
            saved_files["smart_json"] = json_path
        
        all_df = self.to_dataframe(all_metrics)
        all_csv_path = os.path.join(output_dir, f"all_analyzed_{timestamp}.csv")
        all_df.to_csv(all_csv_path, index=False, encoding="utf-8-sig")
        saved_files["all_csv"] = all_csv_path
        
        wallet_list = [m.wallet_address for m in smart_traders]
        wallet_path = os.path.join(output_dir, f"smart_wallets_{timestamp}.json")
        with open(wallet_path, "w", encoding="utf-8") as f:
            json.dump(wallet_list, f, indent=2)
        saved_files["wallets"] = wallet_path
        
        for path in saved_files.values():
            logger.info(f"Saved: {path}")
        
        return saved_files
    
    def run(self, input_file: Optional[str] = None) -> Tuple[List[TraderMetrics], Dict[str, str]]:
        """Run the full analysis pipeline"""
        df = self.load_leaderboard_data(input_file)
        if df.empty:
            return [], {}
        
        df = self.apply_basic_filters(df)
        if df.empty:
            logger.warning("No traders passed basic filters")
            return [], {}
        
        all_metrics = self.analyze_candidates(df)
        smart_traders = self.filter_smart_traders(all_metrics)
        saved_files = self.save_results(smart_traders, all_metrics)
        
        return smart_traders, saved_files


def main():
    """Main entry point for CLI usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze Polymarket traders to find smart money")
    parser.add_argument("--input", type=str, default=None, help="Path to leaderboard CSV/JSON file")
    parser.add_argument("--min-pnl", type=float, default=10000, help="Minimum PnL threshold (default: $10,000)")
    parser.add_argument("--min-volume", type=float, default=50000, help="Minimum volume threshold (default: $50,000)")
    parser.add_argument("--min-win-rate", type=float, default=0.50, help="Minimum win rate (default: 0.50)")
    parser.add_argument("--min-positions", type=int, default=5, help="Minimum closed positions (default: 5)")
    parser.add_argument("--workers", type=int, default=10, help="Number of parallel workers (default: 10)")
    parser.add_argument("--preset", choices=["default", "aggressive", "relaxed"], default="default", help="Use preset configuration")
    
    args = parser.parse_args()
    
    if args.preset == "aggressive":
        config = DiscoveryConfig.aggressive()
    elif args.preset == "relaxed":
        config = DiscoveryConfig.relaxed()
    else:
        config = DiscoveryConfig.default()
    
    config.filter.min_pnl = args.min_pnl
    config.filter.min_volume = args.min_volume
    config.analysis.min_win_rate = args.min_win_rate
    config.analysis.min_closed_positions = args.min_positions
    config.analysis.max_workers = args.workers
    
    analyzer = SmartTraderAnalyzer(config)
    smart_traders, saved_files = analyzer.run(args.input)
    
    print("\n" + "=" * 70)
    print("SMART TRADER ANALYSIS COMPLETE")
    print("=" * 70)
    
    if smart_traders:
        print(f"\nTop 10 Smart Traders:")
        print("-" * 70)
        print(f"{'Rank':<6} {'Address':<44} {'PnL':>12} {'WinRate':>8}")
        print("-" * 70)
        
        for i, trader in enumerate(smart_traders[:10], 1):
            print(f"{i:<6} {trader.wallet_address:<44} ${trader.pnl:>10,.0f} {trader.win_rate:>7.1%}")
        
        print("-" * 70)
        print(f"\nTotal smart traders identified: {len(smart_traders)}")
    else:
        print("\nNo smart traders identified with current criteria.")
    
    if saved_files:
        print(f"\nSaved files:")
        for key, path in saved_files.items():
            print(f"  - {key}: {path}")


if __name__ == "__main__":
    main()
