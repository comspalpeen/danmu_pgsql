# 文件位置: api/config.py (精简后)
import os
from dotenv import load_dotenv

# Load .env from the root directory of the project (moved from common/ to backend_api/common/)
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
load_dotenv(dotenv_path)

# 引入我们刚刚新建的文件
from backend_api.common.user_agents import get_dynamic_headers

# PostgreSQL 配置 
PG_DSN = os.environ.get("PG_DSN")
TIEBA_PG_DSN = os.environ.get("TIEBA_PG_DSN")

REDIS_URL = os.environ.get("REDIS_URL")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET")

if not all([PG_DSN, TIEBA_PG_DSN, REDIS_URL, ADMIN_SECRET]):
    raise ValueError("Missing required environment variables in .env file")

# 兼容老代码的静态 HEADERS，保留它，调用新文件生成一次
HEADERS = get_dynamic_headers()