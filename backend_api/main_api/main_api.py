import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend_api.common.database import lifespan
from routers import check, favorites, legacy, reports, ai_chat,tieba
#, tieba

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册新路由
app.include_router(check.router)
app.include_router(favorites.router)
app.include_router(reports.router)
app.include_router(legacy.router) 
app.include_router(ai_chat.router)
app.include_router(tieba.router)
#app.include_router(tieba.router)
if __name__ == "__main__":
    # 保持您原本能跑通的启动参数，并加上代理信任参数
    uvicorn.run(
        "main_api:app", 
        host="127.0.0.1", 
        port=38324, 
        reload=False,
        proxy_headers=True,         # 👈 关键点 1：开启代理头解析
        forwarded_allow_ips="*"     # 👈 关键点 2：信任来自 Nginx 的 IP 透传
    )