"""
Smart Trader Discovery - Configuration
Configuration file for the discovery module.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class LeaderboardCategory(Enum):
    """Leaderboard categories available in Polymarket API"""
    OVERALL = "OVERALL"
    POLITICS = "POLITICS"
    SPORTS = "SPORTS"
    CRYPTO = "CRYPTO"
    CULTURE = "CULTURE"
    MENTIONS = "MENTIONS"
    WEATHER = "WEATHER"
    ECONOMICS = "ECONOMICS"
    TECH = "TECH"
    FINANCE = "FINANCE"


class LeaderboardTimePeriod(Enum):
    """Time periods for leaderboard data"""
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    ALL = "ALL"


class LeaderboardOrderBy(Enum):
    """Leaderboard ordering criteria"""
    PNL = "PNL"
    VOL = "VOL"


@dataclass
class LeaderboardConfig:
    """Configuration for Leaderboard API fetching"""
    # API limits
    max_offset: int = 1000  # API limit: offset max 1000
    page_size: int = 50  # API limit: 1 <= limit <= 50
    
    # Fetch settings
    categories: List[LeaderboardCategory] = field(
        default_factory=lambda: [LeaderboardCategory.OVERALL]
    )
    time_periods: List[LeaderboardTimePeriod] = field(
        default_factory=lambda: [LeaderboardTimePeriod.ALL]
    )
    order_by: LeaderboardOrderBy = LeaderboardOrderBy.PNL
    
    # Rate limiting
    request_delay_seconds: float = 0.3  # Delay between requests
    max_retries: int = 3
    retry_delay_seconds: float = 2.0


@dataclass
class FilterConfig:
    """Configuration for smart trader filtering thresholds"""
    # PnL thresholds (in USD)
    min_pnl: float = 10000  # Minimum profit/loss
    max_pnl: Optional[float] = None  # Maximum PnL (optional)
    
    # Volume thresholds (in USD)
    min_volume: float = 50000  # Minimum trading volume
    max_volume: Optional[float] = None  # Maximum volume (optional)
    
    # ROI thresholds
    min_roi_percent: Optional[float] = None  # Minimum ROI percentage
    max_roi_percent: Optional[float] = 1000  # Cap extreme ROI (likely anomalies)
    
    # Additional filters
    exclude_market_makers: bool = True  # Filter out known market makers
    exclude_verified: bool = False  # Optionally exclude verified accounts
    max_inactivity_days: int = 14  # Max days since last trade (default: 14)
    
    # Known market maker addresses (to be filtered out)
    market_maker_addresses: List[str] = field(default_factory=list)


@dataclass
class AnalysisConfig:
    """Configuration for deep analysis of traders"""
    # Position analysis
    min_closed_positions: int = 5  # Minimum closed positions for analysis
    max_positions_to_fetch: int = 200  # Maximum positions to fetch per trader
    
    # Win rate thresholds
    min_win_rate: float = 0.50  # Minimum 50% win rate
    
    # Risk metrics
    max_concentration: float = 0.5  # Max position concentration (single market exposure)
    
    # Parallel processing
    max_workers: int = 10  # Number of concurrent threads


@dataclass
class OutputConfig:
    """Configuration for output formats and paths"""
    # Output directory (relative to Find_user folder)
    output_dir: str = "output"
    
    # File formats
    save_csv: bool = True
    save_json: bool = True
    
    # File naming
    timestamp_format: str = "%Y%m%d_%H%M%S"
    
    # Database settings
    save_to_db: bool = False
    db_path: Optional[str] = None


@dataclass
class DiscoveryConfig:
    """Main configuration class combining all settings"""
    leaderboard: LeaderboardConfig = field(default_factory=LeaderboardConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    
    @classmethod
    def default(cls) -> "DiscoveryConfig":
        """Return default configuration"""
        return cls()
    
    @classmethod
    def aggressive(cls) -> "DiscoveryConfig":
        """Return aggressive filter configuration (fewer candidates, higher quality)"""
        return cls(
            filter=FilterConfig(
                min_pnl=25000,
                min_volume=100000,
                min_roi_percent=10,
            ),
            analysis=AnalysisConfig(
                min_closed_positions=10,
                min_win_rate=0.55,
            )
        )
    
    @classmethod
    def relaxed(cls) -> "DiscoveryConfig":
        """Return relaxed filter configuration (more candidates)"""
        return cls(
            filter=FilterConfig(
                min_pnl=5000,
                min_volume=20000,
            ),
            analysis=AnalysisConfig(
                min_closed_positions=3,
                min_win_rate=0.45,
            )
        )


# Default configuration instance
DEFAULT_CONFIG = DiscoveryConfig.default()
