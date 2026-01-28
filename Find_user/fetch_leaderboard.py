"""
Polymarket Leaderboard Fetcher

Fetches Top 1000 traders from Polymarket Leaderboard API.
Supports multiple categories and time periods.

Usage:
    python fetch_leaderboard.py                    # Fetch all data
    python fetch_leaderboard.py --category CRYPTO  # Fetch specific category
    python fetch_leaderboard.py --time-period ALL  # Fetch all-time data
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import json
import time
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from discovery_config import (
    DiscoveryConfig,
    LeaderboardConfig,
    LeaderboardCategory,
    LeaderboardTimePeriod,
    LeaderboardOrderBy,
    DEFAULT_CONFIG,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class LeaderboardFetcher:
    """
    Fetcher for Polymarket Leaderboard API
    
    API: GET https://data-api.polymarket.com/v1/leaderboard
    
    Parameters:
        - category: OVERALL, POLITICS, SPORTS, CRYPTO, CULTURE, etc.
        - timePeriod: DAY, WEEK, MONTH, ALL
        - orderBy: PNL, VOL
        - limit: 1-50 (default 25)
        - offset: 0-1000 (max 1000)
    """
    
    BASE_URL = "https://data-api.polymarket.com/v1/leaderboard"
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, config: Optional[DiscoveryConfig] = None):
        self.config = config or DEFAULT_CONFIG
        self.lb_config = self.config.leaderboard
        
        # Setup session with retry logic
        self.session = self._create_session()
        
        # Cache for fetched data
        self._cache: Dict[str, List[Dict]] = {}
        
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic"""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=self.lb_config.max_retries,
            backoff_factor=self.lb_config.retry_delay_seconds,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        return session
    
    def fetch_page(
        self,
        category: LeaderboardCategory,
        time_period: LeaderboardTimePeriod,
        offset: int,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Fetch a single page from the leaderboard API
        
        Args:
            category: Market category
            time_period: Time period for rankings
            offset: Starting index (0-1000)
            limit: Number of results (1-50)
            
        Returns:
            List of trader dictionaries
        """
        params = {
            "category": category.value,
            "timePeriod": time_period.value,
            "orderBy": self.lb_config.order_by.value,
            "limit": min(limit, 50),
            "offset": min(offset, 1000),
        }
        
        try:
            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Add metadata to each record
            for record in data:
                record["_category"] = category.value
                record["_timePeriod"] = time_period.value
                record["_fetchedAt"] = datetime.now().isoformat()
            
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching page (offset={offset}): {e}")
            return []
    
    def fetch_all_pages(
        self,
        category: LeaderboardCategory,
        time_period: LeaderboardTimePeriod,
        max_traders: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Fetch all pages for a category/time period combination
        
        Args:
            category: Market category
            time_period: Time period for rankings
            max_traders: Maximum number of traders to fetch (max 1000)
            
        Returns:
            List of all trader dictionaries
        """
        all_traders = []
        page_size = self.lb_config.page_size
        max_offset = min(max_traders, self.lb_config.max_offset)
        
        logger.info(f"Fetching leaderboard: {category.value} / {time_period.value}")
        
        # Calculate number of pages
        num_pages = (max_offset + page_size - 1) // page_size
        
        with tqdm(total=num_pages, desc=f"{category.value}-{time_period.value}") as pbar:
            for offset in range(0, max_offset, page_size):
                traders = self.fetch_page(category, time_period, offset, page_size)
                
                if not traders:
                    logger.warning(f"Empty response at offset {offset}, stopping")
                    break
                
                all_traders.extend(traders)
                pbar.update(1)
                
                # Rate limiting
                time.sleep(self.lb_config.request_delay_seconds)
                
                # Early stop if we got fewer results than requested
                if len(traders) < page_size:
                    break
        
        logger.info(f"Fetched {len(all_traders)} traders for {category.value}/{time_period.value}")
        return all_traders
    
    def fetch_all_categories(
        self,
        categories: Optional[List[LeaderboardCategory]] = None,
        time_periods: Optional[List[LeaderboardTimePeriod]] = None,
        max_traders_per_combo: int = 1000
    ) -> pd.DataFrame:
        """
        Fetch leaderboard data for multiple categories and time periods
        
        Args:
            categories: List of categories (default from config)
            time_periods: List of time periods (default from config)
            max_traders_per_combo: Max traders per category/time period
            
        Returns:
            DataFrame with all trader data
        """
        categories = categories or self.lb_config.categories
        time_periods = time_periods or self.lb_config.time_periods
        
        all_data = []
        
        for category in categories:
            for time_period in time_periods:
                traders = self.fetch_all_pages(
                    category,
                    time_period,
                    max_traders_per_combo
                )
                all_data.extend(traders)
        
        if not all_data:
            logger.warning("No data fetched from leaderboard")
            return pd.DataFrame()
        
        df = pd.DataFrame(all_data)
        
        # Deduplicate by proxyWallet, keeping the first occurrence
        if "proxyWallet" in df.columns:
            original_count = len(df)
            df = df.drop_duplicates(subset=["proxyWallet"], keep="first")
            logger.info(f"Deduplicated: {original_count} -> {len(df)} unique traders")
        
        return df
    
    def get_user_profile(self, wallet_address: str) -> Optional[Dict[str, Any]]:
        """
        Fetch user profile from Gamma API
        
        Args:
            wallet_address: User's proxy wallet address
            
        Returns:
            Profile dictionary or None if not found
        """
        url = f"{self.GAMMA_API_URL}/public-profile"
        
        try:
            response = self.session.get(
                url,
                params={"address": wallet_address},
                timeout=30
            )
            
            if response.status_code == 404:
                return None
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching profile for {wallet_address}: {e}")
            return None
    
    def enrich_with_profiles(
        self,
        df: pd.DataFrame,
        max_workers: int = 5
    ) -> pd.DataFrame:
        """
        Enrich trader data with profile information
        
        Args:
            df: DataFrame with proxyWallet column
            max_workers: Number of parallel workers
            
        Returns:
            Enriched DataFrame
        """
        if "proxyWallet" not in df.columns:
            logger.warning("No proxyWallet column found, skipping profile enrichment")
            return df
        
        wallets = df["proxyWallet"].unique().tolist()
        profiles = {}
        
        logger.info(f"Fetching profiles for {len(wallets)} unique wallets")
        
        def fetch_profile(wallet: str) -> tuple:
            time.sleep(0.2)  # Rate limiting
            profile = self.get_user_profile(wallet)
            return (wallet, profile)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(fetch_profile, wallet): wallet
                for wallet in wallets
            }
            
            for future in tqdm(as_completed(futures), total=len(futures), desc="Profiles"):
                wallet, profile = future.result()
                if profile:
                    profiles[wallet] = profile
        
        # Add profile data to DataFrame
        profile_data = []
        for _, row in df.iterrows():
            wallet = row["proxyWallet"]
            profile = profiles.get(wallet, {})
            profile_data.append({
                "profile_bio": profile.get("bio"),
                "profile_name": profile.get("name"),
                "profile_pseudonym": profile.get("pseudonym"),
                "profile_createdAt": profile.get("createdAt"),
                "profile_is_creator": any(
                    u.get("creator", False) 
                    for u in profile.get("users", [])
                ),
                "profile_is_mod": any(
                    u.get("mod", False) 
                    for u in profile.get("users", [])
                ),
            })
        
        profile_df = pd.DataFrame(profile_data)
        return pd.concat([df.reset_index(drop=True), profile_df], axis=1)
    
    def save_results(
        self,
        df: pd.DataFrame,
        prefix: str = "leaderboard"
    ) -> Dict[str, str]:
        """
        Save results to files based on output config
        
        Args:
            df: DataFrame to save
            prefix: File name prefix
            
        Returns:
            Dictionary of saved file paths
        """
        output_config = self.config.output
        
        # Create output directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, output_config.output_dir)
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate timestamp
        timestamp = datetime.now().strftime(output_config.timestamp_format)
        
        saved_files = {}
        
        if output_config.save_csv:
            csv_path = os.path.join(output_dir, f"{prefix}_{timestamp}.csv")
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            saved_files["csv"] = csv_path
            logger.info(f"Saved CSV: {csv_path}")
        
        if output_config.save_json:
            json_path = os.path.join(output_dir, f"{prefix}_{timestamp}.json")
            df.to_json(json_path, orient="records", indent=2, force_ascii=False)
            saved_files["json"] = json_path
            logger.info(f"Saved JSON: {json_path}")
        
        return saved_files


def main():
    """Main entry point for CLI usage"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Fetch Polymarket Leaderboard Data"
    )
    parser.add_argument(
        "--category",
        type=str,
        choices=[c.value for c in LeaderboardCategory],
        default=None,
        help="Market category (default: OVERALL)"
    )
    parser.add_argument(
        "--time-period",
        type=str,
        choices=[t.value for t in LeaderboardTimePeriod],
        default="ALL",
        help="Time period (default: ALL)"
    )
    parser.add_argument(
        "--max-traders",
        type=int,
        default=1000,
        help="Maximum traders to fetch per category (default: 1000)"
    )
    parser.add_argument(
        "--enrich-profiles",
        action="store_true",
        help="Fetch additional profile data (slower)"
    )
    parser.add_argument(
        "--all-categories",
        action="store_true",
        help="Fetch all categories instead of just OVERALL"
    )
    
    args = parser.parse_args()
    
    # Configure fetcher
    config = DiscoveryConfig.default()
    
    if args.all_categories:
        config.leaderboard.categories = list(LeaderboardCategory)
    elif args.category:
        config.leaderboard.categories = [LeaderboardCategory(args.category)]
    
    config.leaderboard.time_periods = [LeaderboardTimePeriod(args.time_period)]
    
    # Run fetcher
    fetcher = LeaderboardFetcher(config)
    
    logger.info("Starting leaderboard fetch...")
    df = fetcher.fetch_all_categories(
        max_traders_per_combo=args.max_traders
    )
    
    if df.empty:
        logger.error("No data fetched, exiting")
        return
    
    # Enrich with profiles if requested
    if args.enrich_profiles:
        df = fetcher.enrich_with_profiles(df)
    
    # Save results
    saved = fetcher.save_results(df)
    
    # Print summary
    print("\n" + "=" * 60)
    print("LEADERBOARD FETCH COMPLETE")
    print("=" * 60)
    print(f"Total traders: {len(df)}")
    
    if "pnl" in df.columns:
        print(f"PnL range: ${df['pnl'].min():,.2f} to ${df['pnl'].max():,.2f}")
    if "vol" in df.columns:
        print(f"Volume range: ${df['vol'].min():,.2f} to ${df['vol'].max():,.2f}")
    
    print(f"\nSaved files:")
    for fmt, path in saved.items():
        print(f"  - {fmt.upper()}: {path}")


if __name__ == "__main__":
    main()
