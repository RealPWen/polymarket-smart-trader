import time
import datetime
import threading
import pandas as pd
from email_notifier import EmailNotifier
from polymarket_data_fetcher import PolymarketDataFetcher
import config
import os

class DailyReportScheduler:
    def __init__(self):
        self.fetcher = PolymarketDataFetcher()
        self.last_report_date = None
        self.check_interval = 60 # Check every minute

    def start(self):
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        print("⏰ [系统] 每日 9:00 AM 定时报告任务已启动")

    def _loop(self):
        while True:
            try:
                # 获取北京时间 (UTC+8)
                tz_offset = datetime.timezone(datetime.timedelta(hours=8))
                now = datetime.datetime.now(tz_offset)
                
                # 检查是否是早上 09:xx (仅发送一次)
                if now.hour == 9 and self.last_report_date != now.date():
                    print(f"⏰ [定时任务] 触发每日报告 ({now.date()})")
                    self._generate_and_send_report(now)
                    self.last_report_date = now.date()
                
                time.sleep(self.check_interval)
            except Exception as e:
                print(f"❌ [定时任务] 出错: {e}")
                time.sleep(60)

    def _generate_and_send_report(self, now):
        try:
            # 1. 确定昨日日期范围 (UTC 时间戳)
            yesterday = now - datetime.timedelta(days=1)
            start_dt = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            yesterday_str = yesterday.strftime('%Y-%m-%d')
            print(f"📊 正在生成 {yesterday_str} 的报表...")

            # 2. 获取我的交易记录 (从 API 或 本地文件)
            # 优先使用 fetcher 获取链上/API 确认的记录
            my_address = config.FUNDER_ADDRESS
            if not my_address:
                print("⚠️ 未配置 FUNDER_ADDRESS，无法生成报告")
                return

            # 获取最近 500 条，然后在内存里过滤
            trades_df = self.fetcher.get_trades(wallet_address=my_address, limit=500, silent=True)
            
            daily_trades = pd.DataFrame()
            daily_pnl = 0.0
            total_cost = 0.0

            if not trades_df.empty:
                # 转换时间戳
                trades_df['dt'] = pd.to_datetime(trades_df['timestamp'], unit='s', utc=True).dt.tz_convert(tz=datetime.timezone(datetime.timedelta(hours=8)))
                
                # 筛选昨日数据
                mask = (trades_df['dt'] >= start_dt) & (trades_df['dt'] <= end_dt)
                daily_trades = trades_df[mask].copy()
                
                if not daily_trades.empty:
                    daily_trades['date'] = daily_trades['dt'] # 用于格式化
                    
                    # 简单估算当日 PnL (仅供参考，复杂 PnL 需要完整 Analyzer)
                    # 这里的逻辑主要是展示流水
                    pass

            # 3. 发送邮件
            # PnL 数据目前还是 dummy 或简单的，如果需要精确 PnL，需要引入 TraderAnalyzer
            # 为了避免引入过多依赖导致复杂，这里先发送基础流水
            
            pnl_info = {
                'daily_pnl': 0.0, # 暂不支持每日精确 PnL 归因
                'total_cost': 0.0 
            }
            
            EmailNotifier.send_daily_report(yesterday_str, pnl_info, daily_trades)
            
        except Exception as e:
            print(f"❌ 生成报告失败: {e}")
