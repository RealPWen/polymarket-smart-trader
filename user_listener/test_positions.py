import os
import requests
import pandas as pd
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def test_fetch_positions():
    # 1. 获取地址
    address = os.getenv("POLYMARKET_FUNDER_ADDRESS")
    if not address:
        print("❌ 错误: .env 中未找到 POLYMARKET_FUNDER_ADDRESS")
        return

    print(f"🔍 正在查询地址: {address}")
    print("-" * 50)

    # 2. 直接构造 API 请求 (绕过所有封装)
    url = "https://data-api.polymarket.com/positions"
    params = {"user": address, "limit": 100}

    try:
        print(f"📡 发送请求至: {url}")
        res = requests.get(url, params=params)
        
        if res.status_code != 200:
            print(f"❌ API 请求失败: Status {res.status_code}")
            print(res.text)
            return

        data = res.json()
        print(f"✅ API 请求成功。返回数据类型: {type(data)}")

        if isinstance(data, list):
            print(f"📊 原始对应行数: {len(data)}")
        else:
            print(f"📊 返回数据非列表: {data}")
            return

        if not data:
            print("⚠️API 返回了空列表 []。说明该账号目前没有任何持仓。")
            return

        # 3. 转换为 DataFrame 方便分析
        df = pd.DataFrame(data)
        
        # 打印列名
        print(f"📋 数据列名: {list(df.columns)}")
        
        # 4. 模拟 app.py 中的过滤逻辑
        if 'size' in df.columns:
            df['size'] = pd.to_numeric(df['size'], errors='coerce').fillna(0)
        
        if 'currentValue' in df.columns:
            df['currentValue'] = pd.to_numeric(df['currentValue'], errors='coerce').fillna(0)
        else:
            print("⚠️  警告: 返回数据中没有 'currentValue' 列！可能会导致过滤错误。")
            df['currentValue'] = 0

        print("\n🔎 --- 原始数据的前 3 行 ---")
        cols_to_show = [c for c in ['asset', 'title', 'outcome', 'size', 'currentValue', 'price'] if c in df.columns]
        if not cols_to_show: cols_to_show = df.columns
        print(df[cols_to_show].head(3).to_string())

        # 5. 应用过滤
        print("\n🧹 --- 应用过滤 (currentValue > 0.01) ---")
        filtered_df = df[df['currentValue'] > 0.01].copy()
        print(f"📊 过滤后剩余行数: {len(filtered_df)}")

        if filtered_df.empty:
            print("⚠️  所有持仓都被过滤掉了！原因可能是 currentValue 都小于 0.01（已归零或极小额）。")
            print("   以下是 value != 0 的行（如果有）：")
            non_zero = df[df['currentValue'] > 0]
            if not non_zero.empty:
                print(non_zero[cols_to_show].to_string())
            else:
                print("   没有 value > 0 的持仓。")
        else:
            print("✅ 有效持仓如下:")
            print(filtered_df[cols_to_show].to_string())

    except Exception as e:
        print(f"❌ 发生异常: {e}")

if __name__ == "__main__":
    test_fetch_positions()
