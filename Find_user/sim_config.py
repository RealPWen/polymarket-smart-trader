"""
Smart Follower Simulation - Configuration
Configuration file for the copy trading simulation module.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SimulationConfig:
    """Configuration for smart follower simulation"""
    
    # Trade simulation parameters
    lookback_count: int = 10  # Number of recent trades to analyze per wallet
    slippage_bps: int = 50  # Assumed slippage in basis points (50 bps = 0.5%)
    sim_amount_per_trade: float = 100.0  # Simulated USDC amount per trade
    min_position_value: float = 1.0  # Skip dust positions below this USDC value
    
    # Statistical calculation parameters
    risk_free_rate: float = 0.0  # For Sharpe/Sortino (default 0 for crypto)
    min_trades_for_stats: int = 5  # Minimum trades required for stat metrics
    
    # Risk thresholds
    max_acceptable_drawdown: float = 0.30  # 30% max drawdown threshold
    min_acceptable_sharpe: float = 0.5  # Minimum Sharpe ratio
    max_acceptable_pvalue: float = 0.10  # Maximum P-value (10% significance)
    
    # API settings
    clob_api_base: str = "https://clob.polymarket.com"
    request_delay_seconds: float = 0.05  # Reduced for speed
    max_retries: int = 3
    
    # Output settings
    output_dir: str = "output"
    save_csv: bool = True
    save_json: bool = True
    
    # Parallel processing
    max_workers: int = 10  # Increased for speed


@dataclass
class SimulationResult:
    """Result of a single wallet simulation"""
    
    wallet_address: str
    trades_simulated: int = 0
    trades_with_price: int = 0  # Trades where current price was available
    
    # PnL metrics
    total_simulated_pnl: float = 0.0
    simulated_roi_percent: float = 0.0
    simulated_win_rate: float = 0.0
    
    # Statistical metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    pvalue: float = 1.0  # Default to 1.0 (not significant)
    kelly_fraction: float = 0.0
    
    # Risk flags
    liquidity_risk: bool = False  # True if order book too thin
    high_drawdown_risk: bool = False
    statistically_significant: bool = False  # True if p < 0.05
    
    # Raw data
    pnl_list: list = field(default_factory=list)
    error_message: Optional[str] = None


# Default configuration instance
DEFAULT_SIM_CONFIG = SimulationConfig()
