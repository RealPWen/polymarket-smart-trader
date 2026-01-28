import json
from datetime import datetime

class BaseTradeHandler:
    """所有处理器的基类"""
    def handle_trade(self, trade_data: dict, listener_context: dict = None):
        """
        处理单笔交易的接口
        :param trade_data: 包含交易详情的字典 (来自 Polymarket API)
        :param listener_context: 监听器的上下文信息 (如被监听的钱包地址等)
        """
        raise NotImplementedError

class ConsoleLogHandler(BaseTradeHandler):
    """
    终端美化输出处理器 (用于实时监控显示)
    """
    is_display = True
    
    def handle_trade(self, trade_data: dict, listener_context: dict = None):
        side = trade_data.get('side', 'UNKNOWN').upper()
        side_emoji = "🟢 BUY" if side == 'BUY' else "🔴 SELL"
        title = trade_data.get('title', 'Unknown Market')
        size = float(trade_data.get('size', 0))
        price = float(trade_data.get('price', 0))
        usd_value = size * price
        
        time_str = datetime.fromtimestamp(trade_data.get('timestamp', 0)).strftime('%H:%M:%S')
        
        print(f"\n[{time_str}] {side_emoji} | {title}")
        print(f"      Size: {size:,.2f} | Price: ${price:.3f} | Total: ${usd_value:,.2f}")
        print(f"      Hash: {trade_data.get('transactionHash')}")

class FileLoggerHandler(BaseTradeHandler):
    """
    文件日志处理器：将所有新交易记录到 jsonl 文件中，方便后续历史分析
    """
    def __init__(self, filename="trade_history.jsonl"):
        import os
        self.filename = filename
        log_dir = os.path.dirname(self.filename)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)

    def handle_trade(self, trade_data: dict, listener_context: dict = None):
        with open(self.filename, 'a', encoding='utf-8') as f:
            log_entry = {
                "monitored_address": listener_context.get('wallet_address') if listener_context else None,
                "recorded_at": datetime.now().isoformat(),
                "trade": trade_data
            }
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

class AutoCopyTradeHandler(BaseTradeHandler):
    """
    自动跟单处理器：提取核心数据，保存为 JSON 并打印
    """
    def __init__(self, save_dir="monitored_trades"):
        import os
        self.save_dir = save_dir
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

    def handle_trade(self, trade_data: dict, listener_context: dict = None):
        # 1. 提取我们关心的核心“干净数据”
        clean_trade = {
            "timestamp": datetime.fromtimestamp(trade_data.get('timestamp', 0)).isoformat(),
            "trader": listener_context.get('wallet_address') if listener_context else "unknown",
            "market": trade_data.get('title'),
            "outcome": trade_data.get('outcome'),
            "side": trade_data.get('side'),
            "size": float(trade_data.get('size', 0)),
            "price": float(trade_data.get('price', 0)),
            "total_usd": float(trade_data.get('size', 0)) * float(trade_data.get('price', 0)),
            "tx_hash": trade_data.get('transactionHash'),
            "condition_id": trade_data.get('conditionId')
        }

        # 2. 打印处理后的 JSON 细节 (方便观察)
        print("\n📥 [处理器] 捕捉到重要订单细节:")
        print(json.dumps(clean_trade, indent=4, ensure_ascii=False))

        # 3. 将单笔订单保存为 JSON 文件 (以哈希命名，防止重复)
        filename = f"{clean_trade['tx_hash'][:14]}.json"
        filepath = f"{self.save_dir}/{filename}"
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(clean_trade, f, indent=4, ensure_ascii=False)
            print(f"💾 订单已存盘: {filepath}")
        except Exception as e:
            print(f"❌ 存盘失败: {e}")

class RealExecutionHandler(BaseTradeHandler):
    """
    实盘下单处理器：真正调用 Polymarket 接口进行买卖
    该处理器不属于 is_display，因此它只处理经过净额过滤后的数据
    """
    def __init__(self, private_key, funder_address, strategy_config=None):
        try:
            from polymarket_trader import PolymarketTrader
            from polymarket_data_fetcher import PolymarketDataFetcher
            self.trader = PolymarketTrader(private_key, funder_address)
            self.fetcher = PolymarketDataFetcher()
            self.strategy = strategy_config or {"mode": 1, "param": 1.0}
            self.last_strategy_mtime = 0
            self.my_address = funder_address
            print(f"🚀 [系统] 实盘下单处理器已就绪 | 模式: {self.strategy['mode']} | 参数: {self.strategy['param']}")
        except Exception as e:
            print(f"❌ [系统] 初始化交易模块失败: {e}")
            self.trader = None

    def _reload_strategy(self):
        """尝试从文件加载最新的策略配置 (带缓存优化)"""
        try:
            import os
            config_path = "monitored_trades/strategy_config.json"
            if os.path.exists(config_path):
                # 获取文件修改时间
                current_mtime = os.path.getmtime(config_path)
                
                # 只有当文件被修改过才重新读取
                if current_mtime > self.last_strategy_mtime:
                    with open(config_path, 'r') as f:
                        new_strategy = json.load(f)
                        # 简单校验
                        if 'mode' in new_strategy and 'param' in new_strategy:
                            if new_strategy != self.strategy:
                                print(f"\n🔄 [策略热更新] 检测到配置变更: {self.strategy} -> {new_strategy}")
                                self.strategy = new_strategy
                            self.last_strategy_mtime = current_mtime
        except Exception as e:
            print(f"⚠️ 策略热更新失败: {e}")

    def handle_trade(self, trade_data: dict, listener_context: dict = None):
        if not self.trader:
            return
            
        import config # 动态读取配置中的阈值
        
        # --- 动态策略热更新 ---
        self._reload_strategy()

        token_id = trade_data.get('asset')


        side = trade_data.get('side', '').upper()
        trader_shares = float(trade_data.get('size', 0))
        price = float(trade_data.get('price', 0))
        trader_amount = trader_shares * price
        
        if not token_id or price <= 0:
            print(f"⚠️ [跳过] 执行层无效数据 (Asset: {token_id}, Price: {price})")
            return

        # 1. 余额预检 (即时预警)
        try:
            # 优先使用 CLOB Client 获取实时余额 (更准)
            my_cash = self.trader.get_balance()
            if my_cash < config.MIN_REQUIRED_USDC:
                print("\n" + "!" * 50)
                print(f"🚨 [账户报警] 余额严重不足!")
                print(f"   当前余额: ${my_cash:.2f} | 设定最小阈值: ${config.MIN_REQUIRED_USDC:.2f}")
                print(f"   系统已进入保护模式，将跳过本次及后续交易。请尽快充值！")
                print("!" * 50 + "\n")
                
                # 发送邮件警报
                try:
                    from .email_notifier import EmailNotifier
                    EmailNotifier.send_low_balance_alert(my_cash, config.MIN_REQUIRED_USDC)
                except Exception as email_err:
                    print(f"⚠️ 邮件发送尝试失败: {email_err}")
                
                return
        except Exception as e:
            print(f"⚠️ [警报系统] 无法通过 CLOB 获取余额，尝试使用 DataAPI: {e}")
            try:
                my_cash = self.fetcher.get_user_cash_balance(self.my_address)
            except:
                my_cash = 999999 

        # --- 计算我的下单金额 (USD) ---
        my_target_amount = 0
        mode = self.strategy['mode']
        param = self.strategy['param']

        if mode == 1:
            my_target_amount = trader_amount * param
        elif mode == 2:
            try:
                trader_address = listener_context.get('wallet_address') if listener_context else None
                trader_cash = self.fetcher.get_user_cash_balance(trader_address)
                
                if trader_cash > 0:
                    portfolio_ratio = trader_amount / trader_cash
                    my_target_amount = portfolio_ratio * my_cash
                    print(f"📊 [比例计算] 交易员占比: {portfolio_ratio:.2%}, 我的余额: ${my_cash:.2f}")
                else:
                    my_target_amount = 0 
            except Exception as e:
                print(f"⚠️ [执行错误] 比例计算失败: {e}")
        elif mode == 3:
            my_target_amount = param

        # 2. 金额二次校验
        if my_target_amount > my_cash:
            print(f"\n⚠️ [余额不足] 目标金额 ${my_target_amount:.2f} 大于当前可用余额 ${my_cash:.2f}，取消下单")
            return

        if my_target_amount < 1.0: # 设置 1 USD 作为最小起步价
            print(f"⏭️ [忽略] 计算出的下单金额 (${my_target_amount:.2f}) 低于系统最小下单门槛 $1.00")
            return
            
        # --- 计算执行价格 ---
        order_type = self.strategy.get('order_type', 'GTC').upper()
        execution_price = round(price, 2) # 基础价格先处理到 2 位
        
        # 如果是市价单 (FOK)，增加滑点容忍度以确保成交
        if order_type == "FOK":
            if side == "BUY":
                execution_price = execution_price + 0.01
            else:
                execution_price = max(0.01, execution_price - 0.01)
            print(f"📊 [市价单模式] 开启滑点保护: ${price:.3f} -> ${execution_price:.2f}")
        
        # --- 计算下单股数 (已加入 SELL 保护逻辑) ---
        my_size = 0
        
        if side == "BUY":
            my_size = int(my_target_amount / execution_price)
        else:
            # 🔴 对于 SELL，我们需要先知道我们手里有多少股
            print(f"🔍 [平仓审计] 正在查询我的持仓以准备卖出...")
            try:
                my_positions = self.fetcher.get_user_positions(self.my_address)
                # 寻找匹配的 token_id
                matched_pos = None
                if not my_positions.empty:
                    # 过滤出当前 token 的持仓
                    curr_pos = my_positions[my_positions['asset'] == token_id]
                    if not curr_pos.empty:
                        matched_pos = float(curr_pos.iloc[0]['size'])
                
                my_holdings = matched_pos if matched_pos else 0
                print(f"📊 [持仓数据] 我当前持有: {my_holdings} 股")
                
                if my_holdings <= 0:
                    print(f"⏭️ [跳过] 交易员在平仓，但我并无该市场持仓。")
                    return
                
                # 计算建议卖出量
                suggested_size = int(my_target_amount / execution_price)
                
                # 🔴 关键保护：卖出量不能超过持仓量
                if suggested_size > my_holdings:
                    my_size = int(my_holdings) # 如果计算量大于持仓，则全平
                    print(f"⚠️ [调整] 计算卖出量超过持仓，已自动调整为全平: {my_size} 股")
                else:
                    my_size = suggested_size
            except Exception as e:
                print(f"⚠️ [持仓查询失败] 将尝试按原计划卖出: {e}")
                my_size = int(my_target_amount / execution_price)

        if my_size < 5:
            print(f"⏭️ [跳过] 计算得出的股数 ({my_size}) 不足 5 股。")
            print(f"    Polymarket 最小下单门槛为 5 股。当前目标金额为 ${my_target_amount:.2f}，执行价为 ${execution_price:.2f}")
            return

        print(f"\n⚡ [实盘执行] 正在下达链上订单...")
        print(f"   策略模式: {mode} | 本笔目标: ${my_target_amount:.2f}")
        print(f"   执行细节: {side} {my_size}股 @ ${execution_price:.2f} (类型: {order_type})")
        
        try:
            result = self.trader.place_order(token_id, side, my_size, execution_price, order_type=order_type)
            print(f"✅ [成交] 订单已提交: {json.dumps(result, ensure_ascii=False)}")
            
            # --- 记录我的成交日志 (供前端展示) ---
            import time
            log_entry = {
                "timestamp": time.time(),
                "date_str": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "strategy": mode,
                "order_type": order_type,
                "trader_base_amount": trader_amount,
                "my_target_amount": my_target_amount,
                "side": side,
                "size": my_size,
                "price": execution_price,
                "market_token": token_id,
                "market_title": trade_data.get('title', 'Unknown Market'),
                "tx_hash": result.get('transactionHash') or result.get('orderID') or "pending" 
            }
            try:
                with open("my_executions.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            except Exception as le:
                print(f"⚠️ 日志写入失败: {le}")

        except Exception as e:
            print(f"❌ [错误] 链上下单失败: {e}")
