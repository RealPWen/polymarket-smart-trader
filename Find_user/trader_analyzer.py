import pandas as pd
import json
from polymarket_data_fetcher import PolymarketDataFetcher


class TraderAnalyzer:
    def __init__(self):
        self.fetcher = PolymarketDataFetcher()
        self.market_cache = {}

    def analyze_trader(self, address: str, limit: int = 500):
        print(f"📊 正在分析交易员: {address} ...")
        
        # 1. 获取交易数据
        trades = self.fetcher.get_trades(wallet_address=address, limit=limit)
        
        if trades.empty:
            print("❌ 未找到交易记录")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        # 2. 数据清洗和盈亏计算
        analysis_df, active_pos_df = self._process_trades(trades)
        
        return analysis_df, trades, active_pos_df

    def _process_trades(self, trades_df):
        """
        处理原始交易数据，计算每笔平仓盈亏和持有到期结算盈亏
        """
        df = trades_df.copy()
        
        # 格式转换
        df['size'] = pd.to_numeric(df['size'], errors='coerce').fillna(0)
        df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)
        df['amount'] = df['size'] * df['price']
        df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
        df['date'] = pd.to_datetime(df['timestamp'], unit='s')
        
        # 按时间正序排列
        df = df.sort_values('date')
        
        # 盈亏计算逻辑 (改进版：支持持有到期)
        
        # 维护持仓: key=(conditionId, outcome), value={'vol': 0, 'cost': 0}
        positions = {} 
        pnl_events = []
        
        # 1. 第一遍扫描：计算 Realized PnL (主动交易产生的盈亏)
        for _, row in df.iterrows():
            cid = row['conditionId']
            side = str(row['side']).strip().upper()
            size = row['size']
            amount = row['amount']
            market_name = row.get('title', 'Unknown Market')
            outcome = row.get('outcome', '-')
            
            key = (cid, outcome)
            
            if key not in positions:
                positions[key] = {
                    'vol': 0, 
                    'cost': 0, 
                    'market_name': market_name, 
                    'slug': row.get('slug'),
                    'last_date': row['date']
                }
                
            pos = positions[key]
            pos['last_date'] = row['date'] # 更新最后活动时间
            
            pnl = 0
            is_close = False
            
            if side == 'BUY':
                pos['vol'] += size
                pos['cost'] += amount
            elif side == 'SELL':
                if pos['vol'] > 0:
                    # 计算该部分持仓的平均成本
                    avg_cost = pos['cost'] / pos['vol'] if pos['vol'] > 0 else 0
                    cost_basis = size * avg_cost
                    
                    # 盈亏 = 卖出所得 - 成本
                    pnl = amount - cost_basis
                    is_close = True
                    
                    # 更新持仓
                    pos['vol'] = max(0, pos['vol'] - size)
                    pos['cost'] = max(0, pos['cost'] - cost_basis)
            
            if is_close:
                pnl_events.append({
                    'date': row['date'],
                    'pnl': pnl,
                    'market': market_name,
                    'outcome': outcome,
                    'type': 'Trade'
                })

        # 2. 第二遍扫描：计算 Settlement PnL (持有到期)
        # 检查所有剩余持仓，如果 Market 已关闭，则计算结算盈亏
        for (cid, outcome), pos in positions.items():
            if pos['vol'] > 0.001: # 忽略极小残余
                market_info = self._get_market_info_cached(cid, slug=pos.get('slug'))
                if not market_info or not market_info.get('closed', False):
                    continue
                
                # 获取结算结果
                try:
                    outcomes_list = json.loads(market_info.get('outcomes', '[]'))
                    prices_list = json.loads(market_info.get('outcomePrices', '[]'))
                except:
                    continue
                    
                if not outcomes_list or not prices_list:
                    continue
                    
                # 判定赢家
                winner_outcome = None
                for idx, price_str in enumerate(prices_list):
                    try:
                        if float(price_str) > 0.95:
                            winner_outcome = outcomes_list[idx]
                            break
                    except:
                        pass
                
                # 计算结算价值
                settlement_val = 0
                if winner_outcome and outcome == winner_outcome:
                    settlement_val = pos['vol'] * 1.0 # 赢了，$1/股
                else:
                    settlement_val = 0 # 输了，归零
                    
                settlement_pnl = settlement_val - pos['cost']
                
                # 结算时间逻辑优化：
                # 1. 默认取最后交易时间
                settle_date = pos['last_date'] 
                
                if market_info.get('closedTime'):
                    try:
                        dt = pd.to_datetime(market_info['closedTime'])
                        # 统一为无时区时间
                        if dt.tzinfo is not None:
                            dt = dt.tz_localize(None)
                            
                        # 核心修复：如果 API 返回的关闭时间早于用户最后交易时间，或者年份异常(比如2020)，
                        # 则强制使用用户的最后交易时间。因为用户不可能在市场关闭很久后还能交易，
                        # 这种通常是 API 脏数据。
                        if dt.year < 2021 or dt < pos['last_date']:
                            settle_date = pos['last_date']
                        else:
                            settle_date = dt
                    except:
                        pass
                
                pnl_events.append({
                    'date': settle_date,
                    'pnl': settlement_pnl,
                    'market': pos['market_name'],
                    'outcome': outcome,
                    'type': 'Settlement'
                })

        # 3. 收集当前活跃仓位 (未平仓且市场未结束)
        active_pos_list = []
        for (cid, outcome), pos in positions.items():
            if pos['vol'] > 0.001:
                market_info = self._get_market_info_cached(cid, slug=pos.get('slug'))
                # 过滤：只有市场未结束的才算“活跃仓位”
                if not market_info or not market_info.get('closed', False):
                    active_pos_list.append({
                        'market': pos['market_name'],
                        'outcome': outcome,
                        'size': pos['vol'],
                        'cost': pos['cost']
                    })
        
        active_pos_df = pd.DataFrame(active_pos_list)
        if not active_pos_df.empty:
            total_cost = active_pos_df['cost'].sum()
            active_pos_df['weight'] = (active_pos_df['cost'] / total_cost * 100) if total_cost > 0 else 0
            active_pos_df = active_pos_df.sort_values('cost', ascending=False)

        # 转换为 DataFrame
        result_df = pd.DataFrame(pnl_events)
        if not result_df.empty:
            result_df = result_df.sort_values('date') # 重新按时间排序
            result_df['cumulative_pnl'] = result_df['pnl'].cumsum()
            
        return result_df, active_pos_df

    def _get_market_info_cached(self, condition_id, slug=None):
        if condition_id in self.market_cache:
            return self.market_cache[condition_id]
            
        try:
            # 优先通过 slug 获取，因为 slug 更唯一且不易出错
            df = pd.DataFrame()
            if slug:
                df = self.fetcher.get_markets(slug=slug)
            
            # 如果 slug 没搜到，再用 condition_id
            if df.empty:
                df = self.fetcher.get_markets(condition_id=condition_id)
            
            if not df.empty:
                # 验证：确保返回的市场 conditionId 真的匹配（防止 API 忽略参数返回默认列表）
                match_row = None
                for _, row in df.iterrows():
                    # 无论 API 返回字段是 conditionId 还是 condition_id，都进行校验
                    fetched_cid = row.get('conditionId') or row.get('condition_id')
                    if fetched_cid and str(fetched_cid).lower() == str(condition_id).lower():
                        match_row = row
                        break
                
                if match_row is not None:
                    info = match_row.to_dict()
                    self.market_cache[condition_id] = info
                    return info
                else:
                    print(f"⚠️ API 返回的市场列表中无匹配的 ConditionID: {condition_id}")
            else:
                print(f"⚠️ API 未返回任何市场数据: {condition_id} / {slug}")

        except Exception as e:
            print(f"⚠️ 获取 Market {condition_id} 失败: {e}")
            pass
        
        self.market_cache[condition_id] = None
        return None

if __name__ == "__main__":
    # 演示代码
    import sys
    ## 0xd235973291b2b75ff4070e9c0b01728c520b0f29 tyson
    ## 0x6022a1784a55b8070de42d19484bbff95fa7c60a tao

    demo_addr = "0xd235973291b2b75ff4070e9c0b01728c520b0f29"
    if len(sys.argv) > 1:
        demo_addr = sys.argv[1]
        
    print(f"🚀 正在运行 TraderAnalyzer 演示 (地址: {demo_addr})...")
    
    analyzer = TraderAnalyzer()
    pnl_df, raw_trades, active_df = analyzer.analyze_trader(demo_addr, limit=10000000)
    
    if not pnl_df.empty:
        print("\n📈 分析结果摘要:")
        print(f"  - 总交易/结算事件数: {len(pnl_df)}")
        print(f"  - 最终累计盈亏: ${pnl_df['cumulative_pnl'].iloc[-1]:.2f}")
        
    if not active_df.empty:
        print("\n� 当前活跃仓位 (Current Positions):")
        print(active_df[['market', 'outcome', 'cost', 'weight']].to_string(index=False))
    else:
        print("\n💰 当前无活跃仓位。")
