# Polymarket Market Scanner & Insider Detector

This module implements advanced algorithms to detect "Smart Money," "Whales," and "Insider Trading" activities on Polymarket. It moves beyond simple PnL rankings to analyze behavioral anomalies and microstructure patterns.

## 🚀 Key Features

### 1. Insider Trading Detection (V4 Anomaly System)
Identifies accounts exhibiting specific patterns of non-public information usage. The V4 engine uses a multi-factor anomaly detection model:

*   **Volume Concentration Anomaly**: Detects users who allocate an abnormally high percentage of their capital (>70%) to a single event and its correlated markets, unlike normal traders who diversify.
*   **Timing Anomaly (One-Shot Detection)**: Identifies accounts that are dormant for long periods, suddenly wake up to trade heavily in a short window (1-2 weeks), and then go dormant again.
*   **Size Anomaly**: Flags trades that are significantly larger (e.g., >100x) than the user's median trade size, indicating high-conviction "sure bets."
*   **Historical Validation**: Uses `closed-positions` API to reconstruct full trading history, catching insiders who have already cashed out and appear inactive on recent activity feeds.

### 2. Whale Burst Scanner (`scanner.py`)
Real-time or historical scanning for aggressive "Whale Bursts" — rapid accumulation of positions that sweeping the order book.
*   **Burst Detection**: Aggregates trades within short windows (e.g., 60s) to find net buying pressure > $2,000.
*   **Directional Filtering**: Filters out arbitrage and hedging by focusing on directional buys at efficient prices (< 0.80).

## 📂 Core Files

| File | Description |
|------|-------------|
| `insider_finder.py` | **Main Tool**. Runs the V4 Insider Detection algorithm. Fetches leaderboard, analyzes full history via Closed Positions, and computes anomaly scores. |
| `scanner.py` | Class definition for the Whale Burst detection logic. |
| `fetch_data.py` | Utility to download raw market and trade data for backtesting. |
| `backtest.py` | Runs the Whale Scanner against historical data to validate signal quality. |
| `debug_insider.py` | Diagnostic tool to deep-dive into a specific wallet address and visualize its anomaly metrics. |

## 📊 Output & Interpretation

Results are saved to the `output/` directory in JSON format. Key metrics to look for in `insider_candidates_v4.json`:

*   **Insider Score**: Composite score (0-500+). Scores > 150 indicate high probability of insider/privileged information.
*   **Concentration Ratio**: `%` of capital in the top event. >70% is highly suspicious.
*   **Anomaly Ratio**: How many times larger the top event volume is compared to the median. >10x is significant.
*   **Signal Tags**: Look for `"EXTREME_CONCENTRATION"`, `"ONE_SHOT_TRADER"`, and `"EXTREME_SIZE_ANOMALY"`.

## 🛠 Usage

**Run Insider Analysis:**
```bash
python insider_finder.py
```
*Scans top 50 leaderboard traders and outputs candidates to `output/insider_candidates_v4.json`.*

**Deep Dive Specific Wallet:**
```bash
# Edit TARGET_ADDRESS in the file first
python debug_insider.py
```

## 🧠 Methodology Notes

*   **Vs. Model Traders**: The algorithm distinguishes Insiders from Model/Quant traders. Model traders typically trade huge volumes across 10+ uncorrelated events. Insiders typically focus on 1-3 specific events where they have an edge.
*   **Data Completeness**: We utilize the `closed-positions` endpoint to ensure potential insiders who exited positions months ago (e.g., 2024 Election) are still caught, even if their recent `activity` log is empty.
