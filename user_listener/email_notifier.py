import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
try:
    from . import config
except ImportError:
    import config
import time
import datetime

class EmailNotifier:
    _last_alert_date = None  # Tracks the date of the last alert

    @staticmethod
    def send_email(subject, body):
        """发送邮件通用方法"""
        if not config.SMTP_USER or not config.SMTP_PASSWORD or not config.EMAIL_RECEIVER:
            print("⚠️ 邮件发送失败: 未配置 SMTP 信息 (SMTP_USER, SMTP_PASSWORD, EMAIL_RECEIVER)")
            return False

        try:
            msg = MIMEMultipart()
            msg['From'] = config.SMTP_USER
            msg['To'] = config.EMAIL_RECEIVER
            msg['Subject'] = subject

            msg.attach(MIMEText(body, 'plain'))

            # 根据端口自动选择 SSL 或 TLS
            if config.SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT)
                # 465 已经是 SSL 连接，不需要 starttls()
            else:
                server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
                server.starttls()
            
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            text = msg.as_string()
            server.sendmail(config.SMTP_USER, config.EMAIL_RECEIVER, text)
            server.quit()
            print(f"📧 邮件已发送给 {config.EMAIL_RECEIVER}: {subject}")
            return True
        except Exception as e:
            print(f"❌ 邮件发送出错: {e}")
            return False

    @classmethod
    def send_low_balance_alert(cls, current_balance, min_required):
        """发送余额不足警报 (每日仅一次)"""
        # 获取北京时间 (UTC+8) 的当前日期
        tz_offset = datetime.timezone(datetime.timedelta(hours=8))
        today = datetime.datetime.now(tz_offset).date()

        # 如果今天已经发送过，直接返回
        if cls._last_alert_date == today:
            return

        subject = f"🚨 [Polymarket] 余额不足警报 (${current_balance:.2f})"
        body = f"""
尊敬的用户:

您的 Polymarket 代理钱包余额已低于设定的最小阈值。

当前余额: ${current_balance:.2f}
最小阈值: ${min_required:.2f}
检测时间: {datetime.datetime.now(tz_offset).strftime('%Y-%m-%d %H:%M:%S')}

系统已暂停新的跟单交易，请尽快充值以恢复服务。

(注: 此报警每日仅触发一次)

Polymarket Trader Bot
        """
        
        if cls.send_email(subject, body):
            cls._last_alert_date = today

    @staticmethod
    def send_daily_report(report_date_str, pnl_data, trades_df):
        """发送每日交易报告"""
        subject = f"📊 [Polymarket] 每日交易简报 ({report_date_str})"
        
        # 简单构建文本表格
        trades_text = "昨日无交易记录"
        if not trades_df.empty:
            trades_lines = []
            for _, row in trades_df.iterrows():
                try:
                    price = float(row.get('price', 0))
                    size = float(row.get('size', 0))
                    side = row.get('side', 'UNKNOWN')
                    title = row.get('title', 'Unknown Market')[:30] + "..."
                    trades_lines.append(f"[{row['date'].strftime('%H:%M')}] {side} {size:.1f}股 @ ${price:.3f} | {title}")
                except: continue
            trades_text = "\n".join(trades_lines)

        body = f"""
尊敬的用户:

这是您的 Polymarket 每日自动交易简报。

📅 报告日期: {report_date_str}

💰 盈亏表现 (昨日估算)
-----------------------
累计盈亏: ${pnl_data.get('daily_pnl', 0):.2f}
总持仓成本: ${pnl_data.get('total_cost', 0):.2f}

📜 昨日订单流 ({len(trades_df)} 笔)
-----------------------
{trades_text}

-----------------------
Polymarket Trader Bot
        """
        return EmailNotifier.send_email(subject, body)
