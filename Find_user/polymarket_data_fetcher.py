"""
Polymarket 数据获取工具
支持 Gamma API 和 Data API
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import json
from typing import Optional, Dict, List, Any
from datetime import datetime


class PolymarketDataFetcher:
    """Polymarket API 数据获取工具类（Gamma API + Data API）"""
    
    def __init__(self):
        self.gamma_api_base = "https://gamma-api.polymarket.com"
        self.data_api_base = "https://data-api.polymarket.com"
        
        # 初始化带重试的 Session
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
    
    # ==================== Gamma API - Events ====================
    
    def get_events(self, active: Optional[bool] = None, closed: Optional[bool] = None, 
                   tag_id: Optional[str] = None, series_id: Optional[str] = None,
                   limit: int = 10, offset: int = 0) -> pd.DataFrame:
        """
        获取事件列表
        
        参数:
            active: 是否只获取活跃事件
            closed: 是否只获取已关闭事件
            tag_id: 按标签ID筛选
            series_id: 按系列ID筛选
            limit: 返回结果数量限制
            offset: 分页偏移量
        
        返回:
            pandas DataFrame 包含事件数据
        """
        url = f"{self.gamma_api_base}/events"
        params = {"limit": limit, "offset": offset}
        
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        if tag_id:
            params["tag_id"] = tag_id
        if series_id:
            params["series_id"] = series_id
        
        return self._make_request(url, params, "事件")
    
    def get_event_by_id(self, event_id: str) -> Dict:
        """获取特定事件的详细信息"""
        url = f"{self.gamma_api_base}/events/{event_id}"
        return self._make_request_json(url, {}, f"事件 {event_id}")
    
    def get_event_by_slug(self, slug: str) -> Dict:
        """通过 slug 获取事件详情"""
        url = f"{self.gamma_api_base}/events-slug/{slug}"
        return self._make_request_json(url, {}, f"事件 slug: {slug}")
    
    # ==================== Gamma API - Markets ====================
    
    def get_markets(self, active: Optional[bool] = None, closed: Optional[bool] = None,
                    event_id: Optional[str] = None, slug: Optional[str] = None,
                    condition_id: Optional[str] = None, limit: int = 10, offset: int = 0) -> pd.DataFrame:
        """
        获取市场列表
        
        参数:
            active: 是否只获取活跃市场
            closed: 是否只获取已关闭市场
            event_id: 按事件ID筛选
            slug: 按slug筛选
            condition_id: 按条件ID筛选
            limit: 返回结果数量限制
            offset: 分页偏移量
        
        返回:
            pandas DataFrame 包含市场数据
        """
        url = f"{self.gamma_api_base}/markets"
        params = {"limit": limit, "offset": offset}
        
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        if event_id:
            params["event_id"] = event_id
        if slug:
            params["slug"] = slug
        if condition_id:
            params["condition_id"] = condition_id
        
        return self._make_request(url, params, "市场")
    
    def get_market_by_id(self, market_id: str) -> Dict:
        """获取特定市场的详细信息"""
        url = f"{self.gamma_api_base}/markets/{market_id}"
        return self._make_request_json(url, {}, f"市场 {market_id}")
    
    def get_markets_from_event(self, event_id: str) -> pd.DataFrame:
        """
        从 Event 对象中直接获取其包含的 Markets
        
        注意: 这个方法比 get_markets(event_id=...) 更可靠，
        因为它直接从 event 对象中提取 markets 数据
        
        参数:
            event_id: 事件ID
        
        返回:
            pandas DataFrame 包含该事件的所有市场数据
        """
        # 先获取 event 详情
        event = self.get_event_by_id(event_id)
        
        if not event:
            print(f"❌ 未找到 Event {event_id}")
            return pd.DataFrame()
        
        # 从 event 中提取 markets
        if 'markets' in event and isinstance(event['markets'], list):
            markets_df = pd.DataFrame(event['markets'])
            print(f"✅ Event {event_id} 包含 {len(markets_df)} 个市场")
            return markets_df
        else:
            print(f"⚠️  Event {event_id} 不包含 markets 数据")
            return pd.DataFrame()
    
    # ==================== Gamma API - Tags & Series ====================
    
    def get_tags(self) -> pd.DataFrame:
        """获取所有可用的标签/分类"""
        url = f"{self.gamma_api_base}/tags"
        return self._make_request(url, {}, "标签")
    
    def get_tag_by_slug(self, slug: str) -> Dict:
        """通过 slug 获取标签详情"""
        url = f"{self.gamma_api_base}/tags-slug/{slug}"
        return self._make_request_json(url, {}, f"标签 slug: {slug}")
    
    def get_series(self, limit: int = 10, offset: int = 0) -> pd.DataFrame:
        """获取事件系列列表"""
        url = f"{self.gamma_api_base}/series"
        params = {"limit": limit, "offset": offset}
        return self._make_request(url, params, "系列")
    
    # ==================== Data API - User Data ====================
    
    def get_user_positions(self, wallet_address: str, limit: int = 100) -> pd.DataFrame:
        """
        获取用户当前持仓
        
        参数:
            wallet_address: 用户钱包地址
            limit: 返回结果数量限制
        
        返回:
            pandas DataFrame 包含持仓数据
        """
        url = f"{self.data_api_base}/positions"
        params = {"user": wallet_address, "limit": limit}
        return self._make_request(url, params, "用户持仓")
    
    def get_user_activity(self, wallet_address: str, limit: int = 100) -> pd.DataFrame:
        """
        获取用户活动记录（交易、存款等）
        
        参数:
            wallet_address: 用户钱包地址
            limit: 返回结果数量限制
        
        返回:
            pandas DataFrame 包含活动数据
        """
        url = f"{self.data_api_base}/activity"
        params = {"user": wallet_address, "limit": limit}
        return self._make_request(url, params, "用户活动")
    
    def get_user_value(self, wallet_address: str) -> Dict:
        """
        获取用户投资组合总价值和表现
        
        参数:
            wallet_address: 用户钱包地址
        
        返回:
            包含价值和表现数据的字典
        """
        url = f"{self.data_api_base}/value"
        params = {"user": wallet_address}
        return self._make_request_json(url, params, "用户价值")
    
    # ==================== Data API - Market Activity ====================
    
    def get_trades(self, market_id: Optional[str] = None, wallet_address: Optional[str] = None,
                   limit: int = 100, offset: int = 0) -> pd.DataFrame:
        """
        获取交易记录 (支持自动分页)
        """
        url = f"{self.data_api_base}/trades"
        all_trades = []
        
        # 内部每次抓取 1000 条 (API 通常上限是 500-1000)
        chunk_size = 1000
        remaining = limit
        current_offset = offset
        
        while remaining > 0:
            fetch_limit = min(chunk_size, remaining)
            params = {"limit": fetch_limit, "offset": current_offset}
            
            if market_id:
                params["market"] = market_id
            if wallet_address:
                params["user"] = wallet_address
            
            try:
                # 不直接用 _make_request 里面的打印，为了静默分页
                response = self.session.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                # 处理不同格式
                batch = []
                if isinstance(data, list):
                    batch = data
                elif isinstance(data, dict):
                    batch = data.get('data', [data] if data else [])
                
                if not batch:
                    break
                    
                all_trades.extend(batch)
                
                if len(batch) < fetch_limit: # 到底了
                    break
                    
                remaining -= len(batch)
                current_offset += len(batch)
                
            except Exception as e:
                print(f"❌ 分页抓取交易失败 at offset {current_offset}: {e}")
                break
        
        df = pd.DataFrame(all_trades)
        if not df.empty:
            print(f"✅ 成功获取 {len(df)} 条交易数据 (Limit: {limit})")
        return df
    
    def get_market_holders(self, market_id: str, limit: int = 100) -> pd.DataFrame:
        """
        获取市场的顶级持有者
        
        参数:
            market_id: 市场 ID (condition ID)
            limit: 返回结果数量限制
        
        返回:
            pandas DataFrame 包含持有者数据
        """
        url = f"{self.data_api_base}/holders"
        params = {"market": market_id, "limit": limit}
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # API 返回的是一个列表，每个元素包含 'token' 和 'holders'
            # 我们需要收集所有 token 的 holders
            all_holders = []
            
            if isinstance(data, list):
                for item in data:
                    if 'holders' in item:
                        holders_list = item['holders']
                        token_id = item.get('token', '')
                        
                        for holder in holders_list:
                            # 添加 token_id 到每个 holder 记录中
                            holder['token_id'] = token_id
                            # 统一 address 字段 (API 返回的是 proxyWallet)
                            if 'proxyWallet' in holder:
                                holder['address'] = holder['proxyWallet']
                            all_holders.append(holder)
            
            if not all_holders:
                return pd.DataFrame()
                
            return pd.DataFrame(all_holders)
            
        except Exception as e:
            print(f"❌ 获取市场持有者失败: {e}")
            return pd.DataFrame()
    

    
    # ==================== Helper Methods ====================
    
    def _make_request(self, url: str, params: Dict, data_type: str) -> pd.DataFrame:
        """发送请求并返回 DataFrame"""
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # 处理不同的响应格式
            if isinstance(data, list):
                df = pd.DataFrame(data)
            elif isinstance(data, dict):
                # 如果是字典，尝试找到数据列表
                if 'data' in data:
                    df = pd.DataFrame(data['data'])
                else:
                    df = pd.DataFrame([data])
            else:
                df = pd.DataFrame()
            
            print(f"✅ 成功获取 {len(df)} 条{data_type}数据")
            return df
            
        except requests.exceptions.RequestException as e:
            print(f"❌ 获取{data_type}数据失败: {e}")
            return pd.DataFrame()
    
    def _make_request_json(self, url: str, params: Dict, data_type: str) -> Dict:
        """发送请求并返回 JSON 字典"""
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            print(f"✅ 成功获取{data_type}数据")
            return data
            
        except requests.exceptions.RequestException as e:
            print(f"❌ 获取{data_type}数据失败: {e}")
            return {}


def main():
    """示例用法"""
    print("=" * 60)
    print("Polymarket 数据获取工具 - 示例")
    print("=" * 60)
    
    # 创建数据获取器实例
    fetcher = PolymarketDataFetcher()
    
    # ==================== Gamma API 示例 ====================
    
    # 1. 获取活跃事件
    print("\n📊 [Gamma API] 获取活跃事件...")
    events_df = fetcher.get_events(active=True, closed=False, limit=5)
    if not events_df.empty:
        print(f"   前3条事件:")
        for idx, row in events_df.head(3).iterrows():
            print(f"   - {row.get('title', 'N/A')}")
    
    # 2. 获取市场数据
    print("\n📈 [Gamma API] 获取市场数据...")
    markets_df = fetcher.get_markets(active=True, closed=False, limit=5)
    if not markets_df.empty:
        print(f"   前3个市场:")
        for idx, row in markets_df.head(3).iterrows():
            print(f"   - {row.get('question', 'N/A')}")
    
    # 3. 获取标签
    print("\n🏷️  [Gamma API] 获取标签...")
    tags_df = fetcher.get_tags()
    if not tags_df.empty:
        print(f"   共 {len(tags_df)} 个标签")
    
    # ==================== Data API 示例 ====================
    
    print("\n💰 [Data API] 获取用户数据...")
    print("   ⚠️  需要提供钱包地址才能获取用户数据")
    print("   示例代码:")
    print("   wallet = '0xYourWalletAddress'")
    print("   positions = fetcher.get_user_positions(wallet)")
    print("   trades = fetcher.get_trades(wallet_address=wallet)")
    

    
    # ==================== 保存数据 ====================
    
    print("\n💾 保存数据到 CSV...")
    if not events_df.empty:
        events_df.to_csv('polymarket_events.csv', index=False, encoding='utf-8-sig')
        print("   ✅ 事件数据已保存到: polymarket_events.csv")
    
    if not markets_df.empty:
        markets_df.to_csv('polymarket_markets.csv', index=False, encoding='utf-8-sig')
        print("   ✅ 市场数据已保存到: polymarket_markets.csv")
    
    if not tags_df.empty:
        tags_df.to_csv('polymarket_tags.csv', index=False, encoding='utf-8-sig')
        print("   ✅ 标签数据已保存到: polymarket_tags.csv")
    
    print("\n" + "=" * 60)
    print("完成！查看 README.md 了解更多用法")
    print("=" * 60)


if __name__ == "__main__":
    main()
