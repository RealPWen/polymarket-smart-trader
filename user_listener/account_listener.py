import pandas as pd
import time
from datetime import datetime
from polymarket_data_fetcher import PolymarketDataFetcher

try:
    from user_listener.trade_handlers import BaseTradeHandler, ConsoleLogHandler
except ImportError:
    from trade_handlers import BaseTradeHandler, ConsoleLogHandler

class AccountListener:
    def __init__(self, wallet_address: str, poll_interval: int = 5):
        self.fetcher = PolymarketDataFetcher()
        self.wallet_address = wallet_address.lower()
        self.poll_interval = poll_interval
        self.last_timestamp = 0
        self.last_hashes = set()
        self.handlers = []

    def add_handler(self, handler: BaseTradeHandler):
        """注册一个新的交易处理器"""
        self.handlers.append(handler)

    def _format_trade(self, trade):
        """格式化输出单条交易信息"""
        ts = datetime.fromtimestamp(trade['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        side = trade['side']
        outcome = trade['outcome']
        size = trade['size']
        price = trade['price']
        title = trade['title']
        tx_hash = trade['transactionHash']
        
        # 简单颜色模拟 (ANSI)
        color = "\033[92m" if side == "BUY" else "\033[91m"
        reset = "\033[0m"
        
        return f"[{ts}] {color}{side}{reset} {size:.2f} @ {price:.3f} | {outcome} | {title} | Hash: {tx_hash[:10]}..."

    def _filter_and_net_trades(self, new_trades_df):
        """
        对一批新交易进行净额结算和过滤。
        如果同一市场在同一批次中出现买入和卖出，且相互抵消（套现），则跳过或仅保留剩余净额。
        """
        if new_trades_df.empty:
            return []
        
        # 转换数字列确保计算正确
        df = new_trades_df.copy()
        df['size'] = pd.to_numeric(df['size'], errors='coerce').fillna(0)
        df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)
        
        final_trades_to_process = []
        
        # 按市场 (conditionId + outcome) 分组
        groups = df.groupby(['conditionId', 'outcome'])
        
        for (cid, outcome), group in groups:
            market_title = group.iloc[0].get('title', 'Unknown Market')
            
            # 计算总买入和总卖出数量
            buys = group[group['side'].str.upper() == 'BUY']
            sells = group[group['side'].str.upper() == 'SELL']
            
            total_buy_size = buys['size'].sum()
            total_sell_size = sells['size'].sum()
            
            # 净额 = 买入 - 卖出
            net_size = total_buy_size - total_sell_size
            
            # 逻辑 A: 如果买卖完全抵消 (例如你说的买 3 卖 3)
            if abs(net_size) < 1e-5:
                if total_buy_size > 0 and total_sell_size > 0:
                    print(f"\n⚡ [过滤] 市场: {market_title}")
                    print(f"   检测到短期套现/完全对冲: 买入({total_buy_size:.2f}) vs 卖出({total_sell_size:.2f})")
                    print(f"   由于该头寸已在该批次内平仓，系统将跳过这些订单流。")
                continue
            
            # 逻辑 B: 如果有净额剩余 (例如你说的买 3 卖 2)
            if net_size > 0:
                # 净买入: 选取最后一条买入作为模板
                template_trade = buys.sort_values('timestamp').iloc[-1].to_dict()
                template_trade['size'] = net_size
                final_trades_to_process.append(template_trade)
                
                if total_sell_size > 0:
                    print(f"\n🌗 [对冲缩减] 市场: {market_title}")
                    print(f"   总买入 {total_buy_size:.2f}, 伴随卖出 {total_sell_size:.2f}。")
                    print(f"   判定为部分持仓，将仅执行净增加部分: {net_size:.2f}")
            else:
                # 净卖出: 选取最后一条卖出作为模板
                template_trade = sells.sort_values('timestamp').iloc[-1].to_dict()
                template_trade['size'] = abs(net_size)
                final_trades_to_process.append(template_trade)
                
                if total_buy_size > 0:
                    print(f"\n🌗 [对冲缩减] 市场: {market_title}")
                    print(f"   总买入 {total_buy_size:.2f}, 伴随卖出 {total_sell_size:.2f}。")
                    print(f"   判定为净减仓，将仅执行净减少部分: {abs(net_size):.2f}")

        # 按原始时间线重排合并后的任务
        final_trades_to_process.sort(key=lambda x: x['timestamp'])
        return final_trades_to_process

    def start_listening(self):
        print(f"🚀 开始监听账户: {self.wallet_address}")
        print(f"⏱️  轮询间隔: {self.poll_interval} 秒")
        print(f"🛡️  净额审计模式: 已开启 (自动过滤短期套现)")
        print("-" * 80)

        # 首次运行时，获取最新的一条作为起点，避免打印历史交易
        try:
            initial_trades = self.fetcher.get_trades(wallet_address=self.wallet_address, limit=1, silent=True)
            if not initial_trades.empty:
                self.last_timestamp = initial_trades.iloc[0]['timestamp']
                self.last_hashes.add(initial_trades.iloc[0]['transactionHash'])
                print(f"📍 设置初始起点: {datetime.fromtimestamp(self.last_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print("⚠️  该账户目前没有任何历史交易。")
        except Exception as e:
            print(f"❌ 初始化失败: {e}")

        while True:
            try:
                now = datetime.now().strftime('%H:%M:%S')
                # 1. 获取最近的交易
                trades_df = self.fetcher.get_trades(wallet_address=self.wallet_address, limit=15, silent=True)
                
                num_fetched = len(trades_df)
                new_count = 0

                if not trades_df.empty:
                    # 2. 筛选真正的新交易
                    new_trades_batch = trades_df[
                        (trades_df['timestamp'] >= self.last_timestamp) & 
                        (~trades_df['transactionHash'].isin(self.last_hashes))
                    ]

                    if not new_trades_batch.empty:
                        # 3. 更新状态（这些 Hash 下次都不会再进入 batch）
                        self.last_timestamp = max(self.last_timestamp, new_trades_batch['timestamp'].max())
                        for h in new_trades_batch['transactionHash'].tolist():
                            self.last_hashes.add(h)

                        # --- A. 原始数据展示 (用于监控显示) ---
                        # 终端用户需要看到每一笔真实的成交流
                        print(f"\n🔔 [捕获原始订单流] {now}")
                        for _, raw_trade in new_trades_batch.sort_values('timestamp').iterrows():
                            trade_dict = raw_trade.to_dict()
                            context = {"wallet_address": self.wallet_address, "now": now}
                            
                            for handler in self.handlers:
                                # 仅 display 类型的处理器接收原始流
                                if getattr(handler, 'is_display', False):
                                    handler.handle_trade(trade_dict, context)

                        # --- B. 净额审计与过滤 (用于实际执行/存盘) ---
                        processed_trades = self._filter_and_net_trades(new_trades_batch)
                        
                        if processed_trades:
                            # 仅在有实际净额变动时，打印执行层面的提示
                            print(f"\n�️  [执行审计] 正在为执行层同步净头寸 (净变动: {len(processed_trades)} 项)...")
                            
                            for trade_dict in processed_trades:
                                context = {"wallet_address": self.wallet_address, "now": now}
                                
                                for handler in self.handlers:
                                    # 非 display 类型的处理器（如存盘、下单等）接收经过过滤的净额数据
                                    if not getattr(handler, 'is_display', False):
                                        handler.handle_trade(trade_dict, context)
                        
                        # 限制 Hash 集合大小
                        if len(self.last_hashes) > 300:
                            self.last_hashes = set(new_trades_batch['transactionHash'].tolist())
                
                # 如果没有新交易，打印心跳
                if new_count == 0:
                    print(f"\r🔍 [{now}] 正在监听... (获取到 {num_fetched} 条历史数据，无净增减仓)", end="", flush=True)

                time.sleep(self.poll_interval)
                
            except KeyboardInterrupt:
                print("\n🛑 停止监听。")
                break
            except Exception as e:
                print(f"❌ 监听出错: {e}")
                time.sleep(self.poll_interval)

if __name__ == "__main__":
    import sys
    
    # 默认账户（用户刚才查询的那个）
    default_wallet = "0xdb27bf2ac5d428a9c63dbc914611036855a6c56e"
    
    target_wallet = sys.argv[1] if len(sys.argv) > 1 else default_wallet
    
    listener = AccountListener(target_wallet)
    
    # 注册默认处理器
    listener.add_handler(ConsoleLogHandler()) # 保持原本的控制台美化显示
    
    # 新增：导入必要的处理器和配置
    from trade_handlers import AutoCopyTradeHandler, FileLoggerHandler, RealExecutionHandler
    import config
    
    # --- 交互式跟单策略选择 ---
    print("\n" + "="*40)
    print("🎯 请选择跟单策略方式:")
    print("1. 按金额比例 (如: 对方下100，你下100 * 比例)")
    print("2. 按仓位占比 (如: 对方下其仓位10%，你也下你仓位10%)")
    print("3. 恒定金额   (如: 无论对方下多少，你固定下 USD 金额)")
    print("="*40)
    
    try:
        choice = input("请输入编号 (1/2/3, 默认1): ").strip() or "1"
        strategy_mode = int(choice)
        strategy_param = 1.0
        
        if strategy_mode == 1:
            val = input("请输入下单比例 (默认 1.0): ").strip() or "1.0"
            strategy_param = float(val)
            print(f"✅ 已选择模式 1: 按金额比例 | 参数: {strategy_param}")
            
        elif strategy_mode == 2:
            print(f"✅ 已选择模式 2: 按仓位占比 (基于实时余额计算)")
            
        elif strategy_mode == 3:
            val = input("请输入单笔恒定金额 USD (默认 50.0): ").strip() or "50.0"
            strategy_param = float(val)
            print(f"✅ 已选择模式 3: 恒定金额 | 单笔: ${strategy_param}")
            
        else:
            print("⚠️ 输入无效，自动切换为模式 1，比例 1.0")
            strategy_mode = 1
            strategy_param = 1.0
            
    except Exception as e:
        print(f"⚠️ 输入错误 ({e})，使用默认设置: 模式 1, 比例 1.0")
        strategy_mode = 1
        strategy_param = 1.0

    strategy_config = {"mode": strategy_mode, "param": strategy_param}
    print("="*40 + "\n")

    # 1. 实盘下单处理器 (核心：真金白银下单)
    # 传递选定的策略配置
    listener.add_handler(RealExecutionHandler(config.PRIVATE_KEY, config.FUNDER_ADDRESS, strategy_config=strategy_config))
    
    # 2. 独立 JSON 文件记录 (每个订单一个文件)
    listener.add_handler(AutoCopyTradeHandler(save_dir=f"monitored_trades/{target_wallet}"))
    
    # 3. 汇总 JSONL 日志记录 (所有订单在一个文件)
    listener.add_handler(FileLoggerHandler(filename=f"monitored_trades/session_{target_wallet}.jsonl"))
    
    listener.start_listening()
