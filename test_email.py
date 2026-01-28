from user_listener.email_notifier import EmailNotifier
from user_listener import config
import time

print("="*60)
print("📧 邮件发送功能自动测试程序")
print("="*60)

# 1. 检查配置
print("\n[1/3] 检查本地环境配置...")
if not config.SMTP_USER:
    print("❌ 错误: 未在 .env 中配置 SMTP_USER")
    exit(1)
if not config.SMTP_PASSWORD:
    print("❌ 错误: 未在 .env 中配置 SMTP_PASSWORD")
    exit(1)
if not config.EMAIL_RECEIVER:
    print("❌ 错误: 未在 .env 中配置 EMAIL_RECEIVER")
    exit(1)

print(f"✅ 发件人: {config.SMTP_USER}")
print(f"✅ 收件人: {config.EMAIL_RECEIVER}")
print(f"✅ 服务器: {config.SMTP_SERVER}:{config.SMTP_PORT}")

# 2. 发送测试邮件
print("\n[2/3] 正在尝试发送测试邮件...")
subject = f"Test Email from Polymarket Bot - {time.time()}"
body = """
这是一封测试邮件。

如果收到此邮件，说明您的 SMTP 配置完全正确。
您的 Polymarket 自动跟单机器人已具备发送警报和日报的能力。

Happy Trading!
"""

start_time = time.time()
success = EmailNotifier.send_email(subject, body)
end_time = time.time()

# 3. 输出结果
print("\n[3/3] 测试结果")
if success:
    print(f"🎉 成功! 邮件已发送，耗时 {end_time - start_time:.2f} 秒")
    print("👉 请检查您的收件箱 (可能在垃圾邮件文件夹中)。")
else:
    print("❌ 失败! 请检查上述报错信息。")
    print("常见原因:")
    print("1. 密码错误 (Gmail 需要使用 'App Password' 而不是登录密码)")
    print("2. 端口错误 (通常 587 用于 TLS, 465 用于 SSL)")
    print("3. 网络问题 (防火墙拦截)")
