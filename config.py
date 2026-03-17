# config.py — 项目根级极简配置（录制程序专用）
# 只包含录制程序需要的公共变量，API 私有配置在 backend_api/common/config.py
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

PG_DSN    = os.environ.get("PG_DSN")
REDIS_URL = os.environ.get("REDIS_URL")
