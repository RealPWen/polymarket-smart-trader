import pandas as pd
import time
import os
from datetime import datetime
from polymarket_data_fetcher import PolymarketDataFetcher

try:
    from user_listener.trade_handlers import BaseTradeHandler, ConsoleLogHandler
except ImportError:
    from trade_handlers import BaseTradeHandler, ConsoleLogHandler

import threading

class AccountListener:
    def __init__(self, wallet_addresses: list, poll_interval: int = 5):
        self.fetcher = PolymarketDataFetcher()
        # 统一转为 list 并去重
        if isinstance(wallet_addresses, str):
            wallet_addresses = [wallet_addresses]
        self.wallet_addresses = list(set([w.lower() for w in wallet_addresses]))
        self.poll_interval = poll_interval
        
        # 每个地址独立维护状态
        # {address: last_timestamp}
        self.state_timestamps = {addr: 0 for addr in self.wallet_addresses}
        # {address: set(last_hashes)}
        self.state_hashes = {addr: set() for addr in self.wallet_addresses}
        
        self.handlers = []
        self.running = False

    def add_handler(self, handler: BaseTradeHandler):
        """注册一个新的交易处理器"""
        self.handlers.append(handler)

    def _filter_and_net_trades(self, new_trades_df):
        """
        对一批新交易进行净额结算和过滤。
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
            
            # 逻辑 A: 如果买卖完全抵消
            if abs(net_size) < 1e-5:
                if total_buy_size > 0 and total_sell_size > 0:
                    print(f"\n⚡ [过滤] 市场: {market_title}")
                    print(f"   检测到短期套现/完全对冲: 买入({total_buy_size:.2f}) vs 卖出({total_sell_size:.2f})")
                continue
            
            # 逻辑 B: 如果有净额剩余
            if net_size > 0:
                # 净买入
                template_trade = buys.sort_values('timestamp').iloc[-1].to_dict()
                template_trade['size'] = net_size
                final_trades_to_process.append(template_trade)
            else:
                # 净卖出
                template_trade = sells.sort_values('timestamp').iloc[-1].to_dict()
                template_trade['size'] = abs(net_size)
                final_trades_to_process.append(template_trade)

        # 按原始时间线重排
        final_trades_to_process.sort(key=lambda x: x['timestamp'])
        return final_trades_to_process

    def _listen_loop(self, target_address):
        """单个地址的监听循环"""
        print(f"🚀 [线程启动] 开始监听: {target_address}")
        
        # 初始化起点
        try:
            initial_trades = self.fetcher.get_trades(wallet_address=target_address, limit=1, silent=True)
            if not initial_trades.empty:
                self.state_timestamps[target_address] = initial_trades.iloc[0]['timestamp']
                self.state_hashes[target_address].add(initial_trades.iloc[0]['transactionHash'])
                print(f"📍 [{target_address[:8]}..] 初始化起点: {datetime.fromtimestamp(self.state_timestamps[target_address]).strftime('%H:%M:%S')}")
            else:
                print(f"⚠️ [{target_address[:8]}..] 无历史交易")
        except Exception as e:
            print(f"❌ [{target_address[:8]}..] 初始化失败: {e}")

        while self.running:
            try:
                # 1. 获取最近的交易
                trades_df = self.fetcher.get_trades(wallet_address=target_address, limit=15, silent=True)
                
                if not trades_df.empty:
                    # 2. 筛选真正的新交易
                    current_last_ts = self.state_timestamps[target_address]
                    current_hashes = self.state_hashes[target_address]
                    
                    new_trades_batch = trades_df[
                        (trades_df['timestamp'] >= current_last_ts) & 
                        (~trades_df['transactionHash'].isin(current_hashes))
                    ]

                    if not new_trades_batch.empty:
                        # 3. 更新状态
                        self.state_timestamps[target_address] = max(current_last_ts, new_trades_batch['timestamp'].max())
                        for h in new_trades_batch['transactionHash'].tolist():
                            self.state_hashes[target_address].add(h)
                            
                        now = datetime.now().strftime('%H:%M:%S')
                        
                        # --- A. 原始数据 (Display) ---
                        print(f"\n🔔 [{target_address[:6]}..] 捕获新交易 | {now}")
                        for _, raw_trade in new_trades_batch.sort_values('timestamp').iterrows():
                            trade_dict = raw_trade.to_dict()
                            context = {"wallet_address": target_address, "now": now}
                            
                            for handler in self.handlers:
                                if getattr(handler, 'is_display', False):
                                    handler.handle_trade(trade_dict, context)

                        # --- B. 净额执行 (Execution) ---
                        processed_trades = self._filter_and_net_trades(new_trades_batch)
                        if processed_trades:
                            for trade_dict in processed_trades:
                                context = {"wallet_address": target_address, "now": now}
                                for handler in self.handlers:
                                    if not getattr(handler, 'is_display', False):
                                        handler.handle_trade(trade_dict, context)
                        
                        # 清理过期的 Hash 缓存
                        if len(self.state_hashes[target_address]) > 300:
                             self.state_hashes[target_address] = set(new_trades_batch['transactionHash'].tolist())

                time.sleep(self.poll_interval)
                # 如果没有新交易，打印心跳
                if new_count == 0:
                    now = datetime.now().strftime('%H:%M:%S') # Re-get current time for heartbeat
                    print(f"\r🔍 [{now}] 正在监听... (获取到 {num_fetched} 条历史数据，无净增减仓)", end="", flush=True)
                    
                    # [新增] 写入心跳文件，方便用户查岗
                    try:
                        # Ensure directory exists
                        os.makedirs("monitored_trades", exist_ok=True)
                        with open("monitored_trades/heartbeat.log", "a") as f:
                            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running...\n")
                    except Exception as file_e: 
                        print(f"⚠️ [{target_address[:8]}..] 写入心跳文件失败: {file_e}")

            except Exception as e:
                print(f"❌ [{target_address[:8]}..] 监听循环出错: {e}")
                time.sleep(self.poll_interval)

    def start_listening(self):
        print(f"🛡️  启动多路监听系统 (共 {len(self.wallet_addresses)} 个目标)")
        print(f"⏱️  轮询间隔: {self.poll_interval} 秒")
        print("-" * 80)
        
        self.running = True
        threads = []
        
        for addr in self.wallet_addresses:
            t = threading.Thread(target=self._listen_loop, args=(addr,), daemon=True)
            t.start()
            threads.append(t)
            time.sleep(0.5) # 错峰启动
            
        try:
            # 主线程保持运行
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 正在停止所有监听线程...")
            self.running = False

if __name__ == "__main__":
    import sys
    import json
    import base64
    from trade_handlers import AutoCopyTradeHandler, FileLoggerHandler, RealExecutionHandler
    import config
    
    # --- 核心锁定：强制读取 ENV 配置 ---
    BOT_WALLET = config.FUNDER_ADDRESS.lower() if config.FUNDER_ADDRESS else None
    TARGET_FROM_ENV = os.getenv("TARGET_TRADER_ADDRESS")
    
    # 确定要监听的目标 (支持逗号分隔)
    arg_target = sys.argv[1] if len(sys.argv) > 1 else None
    
    # 解析目标地址列表
    target_wallets = []
    if arg_target:
        # 支持 "addr1,addr2" 格式
        target_wallets = [t.strip().lower() for t in arg_target.split(',') if t.strip()]
    elif TARGET_FROM_ENV:
        target_wallets = [TARGET_FROM_ENV.lower()]
        
    print("\n" + "🛡️ " * 20)
    print("      POLYMARKET 多路自动化跟单系统启动")
    print("      -----------------------------------")
    print(f"💰 [我的执行钱包] : {BOT_WALLET}")
    print(f"📡 [正在监控目标] : {len(target_wallets)} 个地址")
    for w in target_wallets:
        print(f"   - {w}")
    print("🛡️ " * 20 + "\n")
    
    if not BOT_WALLET or not target_wallets:
        print("❌ 错误：配置不全！请提供至少一个监听地址。")
        sys.exit(1)
        
    # --- 安全熔断器 ---
    for t in target_wallets:
        if BOT_WALLET == t:
            print(f"🚨 [错误] 监听目标包含当前执行钱包 ({t})，系统拒绝启动！")
            sys.exit(1)

    listener = AccountListener(target_wallets)
    
    # 注册默认处理器
    listener.add_handler(ConsoleLogHandler()) 
    
    # 接收 CLI 策略配置
    strategy_config = {"mode": 1, "param": 1.0}
    if len(sys.argv) > 2:
        arg2 = sys.argv[2]
        try:
            strategy_config = json.loads(arg2)
        except:
            try:
                decoded = base64.b64decode(arg2).decode('utf-8')
                strategy_config = json.loads(decoded)
            except: pass
    else:
         # 交互模式仅在单地址时推荐，多地址默认用默认策略以免混乱
         # 这里简化，如果有未传递参数则默认
         if len(target_wallets) == 1:
             # 原有交互逻辑保留给单地址场景，或者完全简化
             pass

    print(f"⚙️  全局策略配置: {strategy_config}")

    # 1. 实盘下单处理器
    listener.add_handler(RealExecutionHandler(config.PRIVATE_KEY, config.FUNDER_ADDRESS, strategy_config=strategy_config))
    
    # 2. 独立 JSON 文件记录
    listener.add_handler(AutoCopyTradeHandler(save_dir=f"monitored_trades/multi_session"))
    
    # 3. 汇总 JSONL 日志记录
    listener.add_handler(FileLoggerHandler(filename=f"monitored_trades/multi_session.jsonl"))
    
    listener.start_listening()
