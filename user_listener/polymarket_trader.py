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
from py_clob_client.clob_types import OrderArgs, OrderType
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
        
        # 签名订单
        signed_order = self.client.create_order(order_args)
        
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


if __name__ == "__main__":
    # 测试示例
    print("Polymarket Trader Module")
    print("Import and use: from polymarket_trader import PolymarketTrader")
