# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

# 加载项目根目录下的 .env 文件
# 强制使用 override=True，确保 .env 中的设置具有最高优先级，不被系统残留环境变量干扰
load_dotenv(override=True) 

# 显式指向根目录 .env
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dotenv = os.path.join(os.path.dirname(current_dir), '.env')
if os.path.exists(root_dotenv):
    load_dotenv(root_dotenv, override=True)

PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS")
SIGNATURE_TYPE = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "1"))
MIN_REQUIRED_USDC = float(os.getenv("MIN_REQUIRED_USDC", "5.0"))

# Email Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "")

# 验证有效性
if FUNDER_ADDRESS:
    # 强制清理地址格式，防止空格等导致的匹配失败
    FUNDER_ADDRESS = FUNDER_ADDRESS.strip().lower()

if not PRIVATE_KEY or not FUNDER_ADDRESS:
    print("⚠️ 警告: 未在 .env 文件中检测到 POLYMARKET_PRIVATE_KEY 或 POLYMARKET_FUNDER_ADDRESS")
