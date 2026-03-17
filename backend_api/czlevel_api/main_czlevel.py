# 文件位置: /www/danmu_pgsql/backend_api/czlevel_api/main_czlevel.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend_api.common.database import lifespan
from routers import czlevel

# ==========================================
# 📦 创建独立的 FastAPI 微服务实例
# ==========================================
app = FastAPI(
    title="CzLevel Microservice",
    description="陈泽粉丝团等级",
    version="1.0.0",
    lifespan=lifespan  
)

# 挂载跨域中间件 (和主程序保持一致，防止前端跨域报错)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 只挂载 czlevel 这一个路由，极致轻量！
app.include_router(czlevel.router)

if __name__ == "__main__":
    # 在独立的端口 (8001) 上运行这个微服务
    uvicorn.run(
        "main_czlevel:app", 
        host="127.0.0.1", 
        port=7458, 
        reload=False,
        proxy_headers=True,         # 信任 Nginx 的代理头
        forwarded_allow_ips="*"     # 获取真实用户 IP 用于限流器
    )