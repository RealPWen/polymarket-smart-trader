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
    def __init__(self, wallet_addresses: list, poll_interval: int = 1):
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
                # 1. 获取最近的交易 (增加 limit 以更好处理高频并发)
                trades_df = self.fetcher.get_trades(wallet_address=target_address, limit=50, silent=True)
                
                num_fetched = len(trades_df)
                new_count = 0
                
                if not trades_df.empty:
                    # 2. 筛选真正的新交易
                    current_last_ts = self.state_timestamps[target_address]
                    current_hashes = self.state_hashes[target_address]
                    
                    new_trades_batch = trades_df[
                        (trades_df['timestamp'] >= current_last_ts) & 
                        (~trades_df['transactionHash'].isin(current_hashes))
                    ]

                    if not new_trades_batch.empty:
                        new_count = len(new_trades_batch)
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
                # 如果没有新交易，打印心跳 (降低频率，每60秒一次)
                if new_count == 0:
                    now = datetime.now().strftime('%H:%M:%S') 
                    # 初始化计数器 (在循环外最好，但这里为了最小化改动，使用取模时间)
                    # 更好的方式: 检查秒数是否为 '00'
                    if now.endswith(':00') or now.endswith(':30'): # 每30秒打印一次
                         # 避免同一秒重复打印 (虽然 sleep(1) 理论上不会)
                         pass
                         # print(f"🔍 [{now}] 正在监听... (系统正常运行中)") # 暂时完全静默，只记录重要事件
                    
                    # 仍然保留心跳文件更新

                    
                    # [新增] 写入心跳文件，方便用户查岗
                    try:
                        # 写入文件到项目根目录
                        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        monitor_dir = os.path.join(root_dir, "monitored_trades")
                        os.makedirs(monitor_dir, exist_ok=True)
                        
                        with open(os.path.join(monitor_dir, "heartbeat.log"), "a") as f:
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
    import config
    import sys
    import json
    import base64
    from trade_handlers import AutoCopyTradeHandler, FileLoggerHandler, RealExecutionHandler
    
    # --- 日志重定向设置 ---
    class DualOutput:
        def __init__(self, filename):
            self.terminal = sys.stdout
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            self.log = open(filename, "a", encoding='utf-8', buffering=1) # 1=line buffered

        def write(self, message):
            self.terminal.write(message)
            self.log.write(message)

        def flush(self):
            self.terminal.flush()
            self.log.flush()

    # 将输出同时重定向到终端和文件
    log_path = os.path.join(os.path.dirname(__file__), 'logs', 'copy_trade.log')
    sys.stdout = DualOutput(log_path)
    sys.stderr = DualOutput(log_path) # 错误也记录

    # --- 使用 argparse 解析参数 ---
    import argparse
    parser = argparse.ArgumentParser(description='Polymarket Account Listener')
    parser.add_argument('targets', nargs='?', help='Comma separated target addresses')
    parser.add_argument('strategy', nargs='?', help='Strategy config JSON/Base64')
    parser.add_argument('--exec-address', help='Execution wallet address (overrides config)')
    parser.add_argument('--exec-key', help='Execution wallet private key (overrides config)')
    
    args = parser.parse_args()

    # 1. 确定监听目标
    arg_target = args.targets
    TARGET_FROM_ENV = config.TARGET_ADDRESS if hasattr(config, 'TARGET_ADDRESS') else None
    TARGET_FROM_ENV = os.getenv("TARGET_TRADER_ADDRESS") # 兼容旧环境
    
    target_wallets = []
    if arg_target:
        target_wallets = [t.strip().lower() for t in arg_target.split(',') if t.strip()]
    elif TARGET_FROM_ENV:
        target_wallets = [TARGET_FROM_ENV.lower()]
        
    # 2. 确定执行钱包 (优先级: CLI参数 > 环境变量 > Config文件)
    BOT_WALLET = args.exec_address
    BOT_PRIVATE_KEY = args.exec_key
    
    if not BOT_WALLET:
        BOT_WALLET = os.getenv("EXEC_WALLET_ADDRESS")
    if not BOT_PRIVATE_KEY:
        BOT_PRIVATE_KEY = os.getenv("EXEC_PRIVATE_KEY")
        
    if not BOT_WALLET:
        BOT_WALLET = config.FUNDER_ADDRESS if hasattr(config, 'FUNDER_ADDRESS') else None
    if not BOT_PRIVATE_KEY:
        BOT_PRIVATE_KEY = config.PRIVATE_KEY if hasattr(config, 'PRIVATE_KEY') else None

    if BOT_WALLET:
        BOT_WALLET = BOT_WALLET.lower()

    # 3. 策略配置解析
    strategy_config = {"mode": 1, "param": 1.0}
    if args.strategy:
        try:
            strategy_config = json.loads(args.strategy)
        except:
            try:
                decoded = base64.b64decode(args.strategy).decode('utf-8')
                strategy_config = json.loads(decoded)
            except: pass
        
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
        if BOT_WALLET and t and BOT_WALLET.lower() == t.lower():
             print(f"⚠️ [警告] 您正在监听自己的执行钱包 ({t})。")
             print("   这可能会导致循环跟单！请确保您知道自己在做什么。")
             # sys.exit(1) # 暂时允许，仅提示警告

    listener = AccountListener(target_wallets)
    
    # 注册默认处理器
    listener.add_handler(ConsoleLogHandler()) 
    
    # 接收 CLI 策略配置 (已由上面的 argparse 处理)
    pass

    print(f"⚙️  全局策略配置: {strategy_config}")

    # 获取项目根目录 (user_listener 的上一级)
    ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MONITOR_DIR = os.path.join(ROOT_DIR, "monitored_trades")
    os.makedirs(MONITOR_DIR, exist_ok=True)

    # 1. 实盘下单处理器
    # 使用动态获取的凭证 (可能是 ENV 传入的，也可能是 Config 回退的)
    listener.add_handler(RealExecutionHandler(BOT_PRIVATE_KEY, BOT_WALLET, strategy_config=strategy_config))
    
    # 2. 独立 JSON 文件记录 (保存到项目根目录/monitored_trades)
    listener.add_handler(AutoCopyTradeHandler(save_dir=os.path.join(MONITOR_DIR, "multi_session")))
    
    # 3. 汇总 JSONL 日志记录 (保存到项目根目录/monitored_trades)
    listener.add_handler(FileLoggerHandler(filename=os.path.join(MONITOR_DIR, "multi_session.jsonl")))
    
    listener.start_listening()
