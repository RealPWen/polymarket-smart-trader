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
