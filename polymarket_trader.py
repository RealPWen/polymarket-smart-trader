# -*- coding: utf-8 -*-
"""
Polymarket 下单模块
支持 Google/Email 登录用户 (Magic Link, signature_type=1)

使用方法:
1. 设置私钥和钱包地址
2. 调用 place_order() 函数

注意事项:
- 私钥从 reveal.polymarket.com 导出
- funder 地址是 Polymarket 上显示的代理钱包地址
- 对于 Google/Email 登录，使用 signature_type=1
"""

import json
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, BalanceAllowanceParams, CreateOrderOptions
from py_clob_client.order_builder.constants import BUY, SELL


class PolymarketTrader:
    """Polymarket 交易类"""
    
    HOST = "https://clob.polymarket.com"
    CHAIN_ID = 137  # Polygon mainnet
    
    def __init__(self, private_key: str, funder_address: str, signature_type: int = 1):
        """
        初始化交易客户端
        
        Args:
            private_key: 从 reveal.polymarket.com 导出的私钥
            funder_address: Polymarket 显示的代理钱包地址
            signature_type: 签名类型
                - 1: Magic/Email/Google 登录 (推荐)
                - 2: 浏览器钱包 (MetaMask等)
                - 0: EOA 直接交易
        """
        self.private_key = private_key
        self.funder_address = funder_address
        self.signature_type = signature_type
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化 CLOB 客户端"""
        # 获取 API 凭证
        temp_client = ClobClient(
            host=self.HOST,
            key=self.private_key,
            chain_id=self.CHAIN_ID
        )
        api_creds = temp_client.create_or_derive_api_creds()
        
        # 创建完整客户端
        self.client = ClobClient(
            host=self.HOST,
            key=self.private_key,
            chain_id=self.CHAIN_ID,
            creds=api_creds,
            signature_type=self.signature_type,
            funder=self.funder_address
        )
        print(f"[OK] Client initialized for {self.funder_address[:10]}...")
    
    def get_orderbook(self, token_id: str) -> dict:
        """获取订单簿"""
        url = f"{self.HOST}/book"
        resp = requests.get(url, params={"token_id": token_id})
        return resp.json()
    
    def get_best_prices(self, token_id: str) -> tuple:
        """获取最佳买卖价格"""
        orderbook = self.get_orderbook(token_id)
        asks = orderbook.get('asks', [])
        bids = orderbook.get('bids', [])
        
        best_ask = float(asks[0]['price']) if asks else None
        best_bid = float(bids[0]['price']) if bids else None
        
        return best_bid, best_ask
    
    def place_order(
        self,
        token_id: str,
        side: str,  # "BUY" or "SELL"
        size: float,
        price: float,
        order_type: str = "GTC"  # "GTC", "FOK", "GTD"
    ) -> dict:
        """
        下单
        
        Args:
            token_id: 代币 ID (YES 或 NO token)
            side: "BUY" 或 "SELL"
            size: 数量 (shares)
            price: 价格 (0.01-0.99)
            order_type: 订单类型
                - "GTC": Good-Til-Cancelled (限价单，直到取消)
                - "FOK": Fill-Or-Kill (全部成交或取消，市价单)
                - "GTD": Good-Til-Date (指定时间前有效)
        
        Returns:
            订单结果字典
        """
        # 验证价格精度 (tick size = 0.01)
        price = round(price, 2)
        
        # 创建订单参数
        order_args = OrderArgs(
            price=price,
            size=size,
            side=BUY if side.upper() == "BUY" else SELL,
            token_id=token_id
        )
        
        # 创建订单选项（重要：包含市场参数）
        options = CreateOrderOptions(
            tick_size="0.01",
            neg_risk=False
        )
        
        # 签名订单
        signed_order = self.client.create_order(order_args, options)
        
        # 选择订单类型
        if order_type.upper() == "FOK":
            ot = OrderType.FOK
        elif order_type.upper() == "GTD":
            ot = OrderType.GTD
        else:
            ot = OrderType.GTC
        
        # 提交订单
        result = self.client.post_order(signed_order, ot)
        
        return result
    
    def buy_yes(self, token_id: str, size: float, price: float = None, market_order: bool = False) -> dict:
        """
        买入 YES
        
        Args:
            token_id: YES token ID
            size: 数量
            price: 价格 (如果 market_order=True，则忽略)
            market_order: 是否市价单
        """
        if market_order:
            _, best_ask = self.get_best_prices(token_id)
            if best_ask:
                price = best_ask
                return self.place_order(token_id, "BUY", size, price, "FOK")
            else:
                raise ValueError("No asks available for market order")
        else:
            if price is None:
                raise ValueError("Price required for limit order")
            return self.place_order(token_id, "BUY", size, price, "GTC")
    
    def get_open_orders(self) -> list:
        """获取所有挂单"""
        return self.client.get_orders()
    
    def cancel_order(self, order_id: str) -> dict:
        """取消订单"""
        return self.client.cancel(order_id)
    
    def cancel_all_orders(self) -> dict:
        """取消所有订单"""
        return self.client.cancel_all()
    
    def get_balance(self) -> float:
        """获取当前账户的 USDC (Collateral) 余额"""
        try:
            # 使用 CLOB Client 获取实时余额
            # asset_type="COLLATERAL" 对应 USDC
            from py_clob_client.clob_types import BalanceAllowanceParams
            params = BalanceAllowanceParams(asset_type="COLLATERAL")
            resp = self.client.get_balance_allowance(params)
            
            # 返回结果中 balance 字段即为余额 (USDC 是 6 位小数)
            if isinstance(resp, dict):
                raw_balance = float(resp.get("balance", 0))
                return round(raw_balance / 1_000_000, 2)
            return 0.0
        except Exception as e:
            # 这里的报错如果是 'dict' object has no attribute 'signature_type'
            # 通常是因为 client 状态异常，我们可以尝试详细打印
            print(f"❌ 获取 CLOB 余额失败: {e}")
            return 0.0


if __name__ == "__main__":
    import config
    import time
    from polymarket_data_fetcher import PolymarketDataFetcher
    
    print("\n" + "="*50)
    print("🧪 Polymarket API 交易功能自测")
    print("="*50)
    
    try:
        trader = PolymarketTrader(config.PRIVATE_KEY, config.FUNDER_ADDRESS)
        fetcher = PolymarketDataFetcher()
        
        # 1. 检查状态
        balance = trader.get_balance()
        print(f"💰 账户余额: ${balance:.2f} USDC")
        
        if balance < 5:
            print("❌ 余额不足 $5，无法进行最小 5 股测试")
            exit()

        # 2. 动态获取一个当前活跃的 Token 进行测试 (避免 ID 过期)
        print("🔍 正在寻找全平台最活跃的市场...")
        trades = fetcher.get_trades(limit=1, silent=True)
        if trades.empty:
            print("❌ 无法获取成交数据，请检查网络")
            exit()
            
        target = trades.iloc[0]
        test_token = target['asset']
        test_price = target['price']
        test_title = target.get('title', 'Unknown')
        
        print(f"✅ 找到活跃市场: {test_title}")
        print(f"   Token: {test_token[:20]}...")
        print(f"   当前参考价: ${test_price}")

        # 3. 提交测试单 (5股，滑点+0.01确保成交)
        test_side = "BUY"
        test_size = 5
        execution_price = round(test_price + 0.01, 2)
        
        print(f"\n🚀 准备下单: {test_side} {test_size}股 @ ${execution_price}")
        confirm = input("⚠️ 是否确认下单？(yes/no): ").strip().lower()
        
        if confirm == 'yes':
            result = trader.place_order(test_token, test_side, test_size, execution_price, order_type="FOK")
            print(f"\n📦 API 响应内容: \n{json.dumps(result, indent=2, ensure_ascii=False)}")
            
            if result.get('success'):
                print("\n✅ [测试成功] 订单已发出！")
                if result.get('status') == 'MATCHED':
                    print("🎉 订单已即时完全成交！")
                else:
                    print(f"📝 订单状态: {result.get('status')} (可能进入等待或延迟列表)")
            else:
                print(f"\n❌ [测试失败] API 返回错误: {result.get('errorMsg')}")
        else:
            print("❌ 测试已手动取消")

    except Exception as e:
        print(f"\n💥 程序运行出错: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*50)
