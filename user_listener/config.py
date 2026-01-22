# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

# 加载项目根目录下的 .env 文件
# 我们假设在项目根目录启动程序，或者 .env 在当前目录
load_dotenv() 

# 也可以尝试加载上级目录的 .env (针对在 user_listener 目录下运行脚本的情况)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dotenv = os.path.join(os.path.dirname(current_dir), '.env')
if os.path.exists(parent_dotenv):
    load_dotenv(parent_dotenv)

PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS")
SIGNATURE_TYPE = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "1"))
MIN_REQUIRED_USDC = float(os.getenv("MIN_REQUIRED_USDC", "5.0"))

if not PRIVATE_KEY or not FUNDER_ADDRESS:
    print("⚠️ 警告: 未在 .env 文件中检测到 POLYMARKET_PRIVATE_KEY 或 POLYMARKET_FUNDER_ADDRESS")
