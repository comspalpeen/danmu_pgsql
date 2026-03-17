# api/database.py
import asyncpg
from redis.asyncio import Redis
from contextlib import asynccontextmanager
from fastapi import FastAPI
from backend_api.common.config import PG_DSN, REDIS_URL, TIEBA_PG_DSN # 引入新配置

pool: asyncpg.Pool = None        # 抖音主池，保持原名
tieba_pool: asyncpg.Pool = None  # 👇 新增：贴吧副池
redis_client: Redis = None

async def init_redis():
    global redis_client
    redis_client = Redis.from_url(REDIS_URL, decode_responses=True)

async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()

async def get_redis() -> Redis:
    return redis_client

async def init_pg():
    """初始化 PostgreSQL 连接池"""
    global pool, tieba_pool
    
    # 1. 抖音主池（原封不动，或者你可以把 max_size 调大点抗并发）
    pool = await asyncpg.create_pool(
            dsn=PG_DSN, 
            min_size=1,            
            max_size=10,           # 建议给抖音多留点连接
            command_timeout=60,    
            timeout=10,            
            max_inactive_connection_lifetime=280, 
    )
    
    # 2. 👇 新增：贴吧压榨副池（极其克制的参数）
    tieba_pool = await asyncpg.create_pool(
            dsn=TIEBA_PG_DSN, 
            min_size=1,            
            max_size=2,            # 极限卡死，最多只能有 2 个并发查询
            command_timeout=20,    # 贴吧查慢了直接杀掉，防死锁
            timeout=15,            
            max_inactive_connection_lifetime=280, 
    )

async def close_pg():
    global pool, tieba_pool
    if pool:
        await pool.close()
    if tieba_pool:
        await tieba_pool.close()

# 获取抖音连接池对象 (原封不动，抖音代码不用改)
def get_db() -> asyncpg.Pool:
    return pool

# 👇 新增：获取贴吧连接池对象
def get_tieba_db() -> asyncpg.Pool:
    return tieba_pool

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 启动 ---
    await init_redis()
    print("✅ [API] Redis 连接成功")
    
    await init_pg()
    print("✅ [API] PostgreSQL 双连接池(抖音主池 / 贴吧副池)初始化成功")
    
    yield
    
    # --- 关闭 ---
    await close_redis()
    await close_pg()
    print("👋 [API] 数据库连接已安全关闭")