import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# 1. 导入路由
from routers import check, favorites, reports, ai_chat, tieba, rooms, authors, search, admin, tools, tools_high_level

# 2. 导入数据库的 lifespan，并起个别名防止命名冲突
from backend_api.common.database import lifespan as db_lifespan

# 3. 导入 Redis 的初始化方法
from src.db.redis_client import init_redis, close_redis

# ==========================================
# 核心修改：合并数据库与 Redis 的生命周期
# ==========================================
@asynccontextmanager
async def global_lifespan(app: FastAPI):
    # --- 启动阶段 ---
    print("🚀 正在初始化全局 Redis...")
    await init_redis() 
    
    # 使用 async with 嵌套启动原有的数据库 lifespan
    async with db_lifespan(app):
        # 此时数据库和 Redis 都已就绪
        yield 
        
    # --- 停止阶段 (服务关闭时执行) ---
    print("👋 正在关闭全局 Redis...")
    await close_redis()

# 将合并后的生命周期挂载到 app 上
app = FastAPI(lifespan=global_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册所有路由
app.include_router(check.router)
app.include_router(favorites.router)
app.include_router(reports.router)
app.include_router(ai_chat.router)
app.include_router(tieba.router)
app.include_router(rooms.router)
app.include_router(authors.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(tools.router)
app.include_router(tools_high_level.router)

if __name__ == "__main__":
    uvicorn.run(
        "main_api:app", 
        host="127.0.0.1", 
        port=38324, 
        reload=False,
        proxy_headers=True,         # 👈 关键点 1：开启代理头解析
        forwarded_allow_ips="*"     # 👈 关键点 2：信任来自 Nginx 的 IP 透传
    )