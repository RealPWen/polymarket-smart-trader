"""
Smart Trader Discovery Pipeline
Orchestrates the entire discovery process: Fetch -> Analyze -> Report
"""

import logging
import sys
import argparse
from datetime import datetime

from discovery_config import DiscoveryConfig, LeaderboardCategory, LeaderboardTimePeriod
from fetch_leaderboard import LeaderboardFetcher
from smart_trader_analyzer import SmartTraderAnalyzer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def run_pipeline(args):
    """Run the full discovery pipeline"""
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("STARTING DISCOVERY PIPELINE")
    logger.info("=" * 60)

    # --- Step 1: Configuration ---
    logger.info("Step 1: Configuring...")
    
    # Load preset if specified
    if args.preset == "aggressive":
        config = DiscoveryConfig.aggressive()
    elif args.preset == "relaxed":
        config = DiscoveryConfig.relaxed()
    else:
        config = DiscoveryConfig.default()

    # Override with specific arguments if provided
    if args.max_traders:
        # Note: In a real scenario, we might want to update the fetch limit logic
        # but for now we pass it to the fetch method
        pass 
        
    # --- Step 2: Fetch Leaderboard ---
    logger.info("Step 2: Fetching Leaderboard Data...")
    fetcher = LeaderboardFetcher(config)
    
    # Setup categories/periods
    categories = [LeaderboardCategory(args.category)] if args.category else None
    time_periods = [LeaderboardTimePeriod(args.time_period)]
    
    df_leaderboard = fetcher.fetch_all_categories(
        categories=categories,
        time_periods=time_periods,
        max_traders_per_combo=args.max_traders
    )
    
    if df_leaderboard.empty:
        logger.error("No leaderboard data fetched. Aborting.")
        return

    # Enrich profiles if requested
    if args.enrich_profiles:
        logger.info("Enriching with profile data...")
        df_leaderboard = fetcher.enrich_with_profiles(df_leaderboard)

    # Save raw leaderboard data
    fetcher.save_results(df_leaderboard, prefix="pipeline_raw")
    
    # --- Step 3: Analyze & Filter ---
    logger.info("Step 3: Analyzing Candidates...")
    analyzer = SmartTraderAnalyzer(config)
    
    # Run analysis directly on the dataframe we just fetched
    # We skip the load_leaderboard_data step since we already have the df
    df_filtered = analyzer.apply_basic_filters(df_leaderboard)
    
    if df_filtered.empty:
        logger.warning("No candidates passed basic filters.")
        return

    all_metrics = analyzer.analyze_candidates(df_filtered)
    smart_traders = analyzer.filter_smart_traders(all_metrics)
    
    # --- Step 4: Save & Report ---
    logger.info("Step 4: Saving Results...")
    saved_files = analyzer.save_results(smart_traders, all_metrics, prefix="pipeline_smart")
    
    duration = datetime.now() - start_time
    
    print("\n" + "=" * 60)
    print(f"PIPELINE COMPLETED in {duration}")
    print("=" * 60)
    print(f"Total Scanned: {len(df_leaderboard)}")
    print(f"Candidates:    {len(all_metrics)}")
    print(f"Smart Traders: {len(smart_traders)}")
    print("-" * 60)
    
    if smart_traders:
        print(f"Top 5 Smart Traders:")
        for idx, t in enumerate(smart_traders[:5]):
            print(f"{idx+1}. {t.wallet_address} (PnL: ${t.pnl:,.0f}, Win: {t.win_rate:.0%})")
    
    print("\nOutput Files:")
    for key, path in saved_files.items():
        print(f"- {key}: {path}")


def main():
    parser = argparse.ArgumentParser(description="Run Smart Trader Discovery Pipeline")
    
    # Pipeline options
    parser.add_argument("--preset", choices=["default", "aggressive", "relaxed"], default="default",
                      help="Configuration preset")
    
    # Fetch options
    parser.add_argument("--max-traders", type=int, default=1000,
                      help="Max traders to fetch per category")
    parser.add_argument("--category", type=str, default="OVERALL",
                      choices=[c.value for c in LeaderboardCategory],
                      help="Market category")
    parser.add_argument("--time-period", type=str, default="ALL",
                      choices=[t.value for t in LeaderboardTimePeriod],
                      help="Time period")
    parser.add_argument("--enrich-profiles", action="store_true",
                      help="Fetch detailed profiles (slower)")
    
    args = parser.parse_args()
    
    try:
        run_pipeline(args)
    except KeyboardInterrupt:
        print("\nPipeline stopped by user.")
    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")

if __name__ == "__main__":
    main()
