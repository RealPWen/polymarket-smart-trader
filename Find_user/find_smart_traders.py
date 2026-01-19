"""
Polymarket 聪明钱猎手 (Smart Trader Finder) - 高速版 🚀

功能：
1. 并行扫描市场挖掘潜在的交易高手。
2. 并行深度分析每个候选人的历史交易记录。
3. 计算胜率、盈亏比、总利润等核心指标。
4. 筛选并推荐值得跟单的“胜率之王”。
"""

from polymarket_data_fetcher import PolymarketDataFetcher
import pandas as pd
import numpy as np
import time
from collections import defaultdict
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm  # 进度条支持
import json

class SmartTraderFinder:
    def __init__(self, max_workers=10):
        self.fetcher = PolymarketDataFetcher()
        self.analyzed_traders = {} 
        self.max_workers = max_workers # 并行线程数
        
    def scan_markets_for_candidates(self, active_limit=10, closed_limit=5, holders_per_market=10):
        """
        [并行] 扫描市场获取候选人地址列表
        """
        candidates = set()
        
        print(f"🔍 正在扫描市场挖掘候选人 (并行线程: {self.max_workers})...")
        
        # 1. 获取所有 Event
        active_events = self.fetcher.get_events(active=True, closed=False, limit=active_limit)
        closed_events = self.fetcher.get_events(active=False, closed=True, limit=closed_limit)
        
        all_events = []
        if not active_events.empty:
            all_events.extend(active_events['id'].tolist())
        if not closed_events.empty:
            all_events.extend(closed_events['id'].tolist())
            
        print(f"   - 共发现 {len(all_events)} 个事件，开始提取 Markets...")

        # 2. 提取所有 conditionIds
        all_condition_ids = []
        
        # 这里为了简单，Event 信息的获取还是串行比较稳妥，或者也可以并行
        # 我们先并行获取 Markets
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_event = {executor.submit(self.fetcher.get_markets_from_event, str(eid)): eid for eid in all_events}
            
            for future in tqdm(as_completed(future_to_event), total=len(all_events), desc="抓取 Events"):
                try:
                    markets_df = future.result()
                    if not markets_df.empty and 'conditionId' in markets_df.columns:
                        # 限制每个 Event 只取前 5 个 Market，避免过多冷门
                        cond_ids = markets_df['conditionId'].dropna().unique()[:5]
                        all_condition_ids.extend(cond_ids)
                except Exception:
                    pass
        
        print(f"   - 提取到 {len(all_condition_ids)} 个活跃 Markets，正在挖掘 Top Holders...")
        
        # 3. [并行] 获取所有 Markets 的 Holders
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交任务
            future_to_cid = {
                executor.submit(self.fetcher.get_market_holders, cid, limit=holders_per_market): cid 
                for cid in all_condition_ids
            }
            
            # 处理结果
            for future in tqdm(as_completed(future_to_cid), total=len(all_condition_ids), desc="挖掘 Holders"):
                try:
                    holders_df = future.result()
                    if not holders_df.empty and 'address' in holders_df.columns:
                        new_candidates = holders_df['address'].tolist()
                        candidates.update(new_candidates)
                except Exception:
                    pass
                    
        print(f"✅ 挖掘完成! 共找到 {len(candidates)} 个唯一候选交易者")
        return list(candidates)

    def analyze_trader_performance(self, address, trade_limit=200):
        """
        深度分析单个交易者的表现
        """
        if address in self.analyzed_traders:
            return self.analyzed_traders[address]
            
        try:
            # 获取交易记录
            trades = self.fetcher.get_trades(wallet_address=address, limit=trade_limit)
            
            if trades.empty:
                return None
                
            stats = self._calculate_stats(trades)
            stats['address'] = address
            
            self.analyzed_traders[address] = stats
            return stats
            
        except Exception as e:
            return None

    def _calculate_stats(self, trades_df):
        """
        计算交易统计指标 (核心算法)
        改进版：包含持有到期 (Held to Maturity) 的盈亏计算
        """
        if trades_df.empty:
            return {'win_rate': 0, 'total_pnl': 0, 'trade_count': 0, 'profit_factor': 0}
            
        trades_df = trades_df.copy()
        # 优化：一次性转换
        trades_df[['size', 'price']] = trades_df[['size', 'price']].apply(pd.to_numeric, errors='coerce').fillna(0)
        trades_df['amount'] = trades_df['size'] * trades_df['price']
        
        # 按 (Market, Outcome) 分组，因为不同 Outcome 是不同资产
        groups = trades_df.groupby(['conditionId', 'outcome'])
        
        total_pnl = 0
        wins = 0
        losses = 0
        total_profit = 0
        total_loss = 0
        participated_markets = set()
        
        # 记录剩余持仓以便后续检查结算状态
        # key: (conditionId, outcome), value: {'vol': float, 'cost': float}
        remaining_positions = {}
        
        for (cid, outcome), group in groups:
            participated_markets.add(cid)
            
            buys = group[group['side'] == 'BUY']
            sells = group[group['side'] == 'SELL']
            
            buy_vol = buys['size'].sum()
            sell_vol = sells['size'].sum()
            
            if buy_vol == 0: continue
            
            buy_amt = buys['amount'].sum()
            sell_amt = sells['amount'].sum()
            
            # 1. 计算已平仓部分的盈亏 (Realized PnL from Sells)
            realized_pnl = 0
            avg_buy_price = buy_amt / buy_vol
            
            if sell_vol > 0:
                cost_of_sold = sell_vol * avg_buy_price
                realized_pnl = sell_amt - cost_of_sold
                
                total_pnl += realized_pnl
                
                if realized_pnl > 0.01:
                    wins += 1
                    total_profit += realized_pnl
                elif realized_pnl < -0.01:
                    losses += 1
                    total_loss += abs(realized_pnl)
            
            # 2. 记录剩余持仓 (Remaining Position)
            rem_vol = buy_vol - sell_vol
            if rem_vol > 0.001: # 忽略微小尘埃
                rem_cost = rem_vol * avg_buy_price
                remaining_positions[(cid, outcome)] = {'vol': rem_vol, 'cost': rem_cost}

        # 3. 处理持有到期 (Settlement PnL)
        # 检查所有剩余持仓的市场是否已关闭并结算
        if remaining_positions:
            unique_cids = set(k[0] for k in remaining_positions.keys())
            
            for cid in unique_cids:
                # 获取 Market Info (优先查缓存)
                market_info = self._get_market_info_cached(cid)
                
                if not market_info:
                    continue
                    
                # 检查是否已关闭
                is_closed = market_info.get('closed', False)
                if is_closed:
                    # 获取结果
                    try:
                        outcomes = json.loads(market_info.get('outcomes', '[]'))
                        prices = json.loads(market_info.get('outcomePrices', '[]'))
                    except:
                        continue
                        
                    if not outcomes or not prices or len(outcomes) != len(prices):
                        continue
                        
                    # 确定赢家 (价格约为 1 的 outcome)
                    # 注意：通常赢家价格是 "1" 或非常接近 1
                    winner_outcome = None
                    for idx, price_str in enumerate(prices):
                        try:
                            if float(price_str) > 0.95:
                                winner_outcome = outcomes[idx]
                                break
                        except:
                            pass
                    
                    # 检查此 CID 下该用户持有的 outcome
                    for (r_cid, r_outcome), pos in remaining_positions.items():
                        if r_cid != cid: continue
                        
                        pnl = 0
                        vol = pos['vol']
                        cost = pos['cost']
                        
                        if winner_outcome and r_outcome == winner_outcome:
                            # 赢了：价值变为 $1.00 * vol
                            settlement_value = vol * 1.0
                            pnl = settlement_value - cost
                            # print(f"  [Settlement Win] Match: {cid} | PnL: {pnl:.2f}")
                        else:
                            # 输了 (或者找不到赢家但市场关了)：价值归零
                            pnl = 0 - cost
                            # print(f"  [Settlement Loss] Match: {cid} | PnL: {pnl:.2f}")

                        total_pnl += pnl
                        if pnl > 0.01:
                            wins += 1
                            total_profit += pnl
                        elif pnl < -0.01:
                            losses += 1
                            total_loss += abs(pnl)

        total_closed_trades = wins + losses
        win_rate = wins / total_closed_trades if total_closed_trades > 0 else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else (999 if total_profit > 0 else 0)
        
        return {
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_profit': total_profit,
            'total_loss': total_loss,
            'profit_factor': profit_factor,
            'trade_count': len(trades_df), # 这里仅作参考
            'market_count': len(participated_markets),
            'closed_count': total_closed_trades
        }

    def _get_market_info_cached(self, condition_id):
        """Helper to fetch market info with caching"""
        if not hasattr(self, 'market_cache'):
            self.market_cache = {}
            
        if condition_id in self.market_cache:
            return self.market_cache[condition_id]
            
        try:
            # 使用 get_markets 筛选来获取详情，因为 get_market_by_id 对某些 ID 格式支持不好
            df = self.fetcher.get_markets(condition_id=condition_id)
            if not df.empty:
                # 转换为 dict 并缓存
                info = df.iloc[0].to_dict()
                self.market_cache[condition_id] = info
                return info
        except Exception:
            pass
            
        self.market_cache[condition_id] = None
        return None

    def run(self, min_win_rate=0.5, min_trades=3, min_profit=0, active_scan=10, closed_scan=5, testing=True):
        print("🚀 启动 Smart Trader 猎手 (高速多线程版)...")
        print(f"🎯 筛选目标: 胜率>{min_win_rate:.0%} | 场次>={min_trades} | 盈利>${min_profit}")
        if testing:
            print("🧪 测试模式: 开启 (将保存所有分析过的交易者数据)")
        print("==================================================")
        
        # 1.获取候选人
        candidates = self.scan_markets_for_candidates(active_limit=active_scan, closed_limit=closed_scan)
        
        # 2. [并行] 深度分析
        print(f"\n🔬 开始深度分析 {len(candidates)} 位候选人...")
        
        smart_traders = []
        all_traders_stats = [] # 用于测试模式，存储所有人
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_addr = {executor.submit(self.analyze_trader_performance, addr): addr for addr in candidates}
            
            for future in tqdm(as_completed(future_to_addr), total=len(candidates), desc="分析 Traders"):
                try:
                    stats = future.result()
                    if stats:
                        # 收集基础数据
                        all_traders_stats.append(stats)
                        
                        # 动态筛选 smart traders
                        if (stats['closed_count'] >= min_trades 
                            and stats['win_rate'] >= min_win_rate
                            and stats['total_pnl'] >= min_profit):
                            smart_traders.append(stats)
                except Exception:
                    pass
            
        print("\n✅ 分析完成!")
        
        # 3. 决定要保存和展示的数据集
        if testing:
            target_list = all_traders_stats
            print(f"🧪 测试模式: 共分析了 {len(target_list)} 位交易者，准备全部导出。")
            csv_filename = "traders_debug_all.csv"
        else:
            if not smart_traders:
                print("⚠️ 未找到符合条件的 Smart Trader。建议降低筛选标准 (或使用 --testing 查看所有分析结果)。")
                return
            target_list = smart_traders
            csv_filename = "traders_pool.csv"

        # 评分算法优先按胜率排序
        ranked_traders = sorted(
            target_list,
            key=lambda x: (x['win_rate'], x['total_pnl']),
            reverse=True
        )
        
        print(f"\n🏆 SMART TRADERS 排行榜 (Top 15) [共筛选出 {len(ranked_traders)} 人]")
        print("="*90)
        print(f"{'排名':<5} {'地址':<44} {'胜率':<8} {'总盈亏($)':<12} {'盈亏比':<8} {'场次':<8}")
        print("-" * 90)
        
        # 展示 Top 15
        top_n_traders = ranked_traders[:15]
        
        for rank, t in enumerate(top_n_traders, 1):
            addr_display = t['address']
            print(f"{rank:<5} {addr_display:<44} {t['win_rate']:.1%}    {t['total_pnl']:<12.2f} {t['profit_factor']:<8.2f} {t['closed_count']:<8}")
            
        # 导出结果
        if ranked_traders:
            df = pd.DataFrame(ranked_traders)
            df.to_csv(csv_filename, index=False)
            print(f"\n💾 榜单已保存至: {csv_filename}")
        
        # 推荐最佳人选 (如果有的话)
        if ranked_traders:
            best = ranked_traders[0]
            print("\n🌟 最佳跟单推荐:")
            print(f"地址: {best['address']}")
            print(f"核心数据: 胜率 {best['win_rate']:.1%} | 盈亏 ${best['total_pnl']:.2f} | 盈亏比 {best['profit_factor']:.2f}")
            print(f"Polymarket Profile: https://polymarket.com/profile/{best['address']}")

if __name__ == "__main__":
    import argparse
    
    # 自动安装依赖
    try:
        from tqdm import tqdm
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "tqdm"])
        from tqdm import tqdm

    parser = argparse.ArgumentParser(description='Polymarket Smart Trader Finder')
    
    # 核心筛选超参
    parser.add_argument('--min-win', type=float, default=0.5, help='最小胜率 (0.0-1.0), 默认 0.5')
    parser.add_argument('--min-trades', type=int, default=3, help='最小有效交易场次, 默认 3')
    parser.add_argument('--min-profit', type=float, default=0, help='最小总盈利($), 默认 0')
    
    # 扫描与运行超参
    parser.add_argument('--scan-active', type=int, default=10, help='扫描活跃事件数量, 默认 10')
    parser.add_argument('--scan-closed', type=int, default=5, help='扫描已结束事件数量, 默认 5')
    parser.add_argument('--workers', type=int, default=10, help='并发线程数, 默认 10')
    
    # 新增 testing 参数 (默认开启，使用 --no-testing 关闭)
    parser.add_argument('--no-testing', action='store_false', dest='testing', help='关闭测试模式')
    parser.set_defaults(testing=True)
    
    args = parser.parse_args()

    finder = SmartTraderFinder(max_workers=args.workers)
    finder.run(
        min_win_rate=args.min_win,
        min_trades=args.min_trades,
        min_profit=args.min_profit,
        active_scan=args.scan_active,
        closed_scan=args.scan_closed,
        testing=args.testing
    )
