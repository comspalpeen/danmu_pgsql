import asyncio
import aiohttp
import orjson as json
import uuid
import urllib.parse
import logging
from datetime import datetime, date
from html import escape
from typing import List

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse

from backend_api.common.database import get_db
from src.db.redis_client import get_redis
from backend_api.common.models import HighLevelFanItem, ExportNewRequest, ScanStatusResponse

# 配置专属日志
logger = logging.getLogger("RadarScan")
logger.setLevel(logging.INFO)

router = APIRouter(tags=["tools_high_level"])

# ==========================================
# 1. HTML 渲染模板 (稳定输出)
# ==========================================
def render_fans_html(fans: List[dict], title: str) -> str:
    level_counts = {20: 0, 19: 0, 18: 0, 17: 0, 16: 0}
    for f in fans:
        lvl = f.get("club_level", 0)
        if lvl in level_counts:
            level_counts[lvl] += 1

    current_time = int(datetime.now().timestamp())
    cards_html = ""
    
    for idx, user in enumerate(fans, 1):
        intimacy = user.get("intimacy", 0)
        participate_time = user.get("participate_time", 0)
        avatar_url = user.get("avatar_url", "") or "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
        
        intimacy_wan = f"{intimacy / 10000:.1f}万" if intimacy >= 10000 else str(intimacy)
        days = (current_time - participate_time) // 86400 if participate_time > 0 else 0
        duration_str = f"{days}天" if days > 0 else "未知"
        profile_url = f"https://www.iesdouyin.com/share/user/{user.get('sec_uid')}"

        cards_html += f"""
        <div class="user-card">
            <div class="user-idx">NO.{idx}</div>
            <img src="{avatar_url}" alt="avatar" class="avatar" onerror="this.src='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';this.style.background='#eee';">
            <div class="info">
                <div class="row-1">
                    <span class="nickname" title="{escape(user.get('nickname',''))}">{escape(user.get('nickname',''))}</span>
                    <span class="badge-level">Lv.{user.get('club_level')}</span>
                </div>
                <div class="row-2">
                    <span class="display-id">ID: {escape(user.get('display_id',''))}</span>
                    <a href="{profile_url}" target="_blank" class="link-btn">访问主页</a>
                </div>
                <div class="row-3">
                    <span class="tag">亲密度: {intimacy_wan}</span>
                    <span class="tag">入团: {duration_str}</span>
                </div>
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>{title}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f2f2f6; margin: 0; padding: 16px 12px; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; }}
        .header-card {{ background: linear-gradient(135deg, #ff2a40, #ff6a80); color: white; border-radius: 12px; padding: 16px; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(255,42,64,0.3); }}
        .header-card h2 {{ margin: 0 0 15px 0; font-size: 1.1rem; text-align: center; font-weight: 600; letter-spacing: 1px; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; text-align: center; }}
        .stat-item {{ background: rgba(255,255,255,0.2); padding: 8px 0; border-radius: 8px; }}
        .stat-level {{ font-size: 0.75rem; opacity: 0.9; }}
        .stat-count {{ font-size: 1.1rem; font-weight: bold; margin-top: 4px; }}
        .user-card {{ background: white; border-radius: 12px; padding: 16px; margin-bottom: 12px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); display: flex; align-items: center; position: relative; overflow: hidden; }}
        .user-idx {{ position: absolute; top: 0; left: 0; background: #ffe4e6; color: #e11d48; font-size: 0.65rem; font-weight: bold; padding: 3px 8px; border-radius: 0 0 8px 0; }}
        .avatar {{ width: 54px; height: 54px; border-radius: 50%; object-fit: cover; margin-right: 14px; border: 1px solid #f0f0f0; background-color: #f9f9f9; }}
        .info {{ flex: 1; min-width: 0; margin-top: 6px; }}
        .row-1 {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
        .nickname {{ font-weight: 600; font-size: 1rem; color: #111; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 60%; }}
        .badge-level {{ background: linear-gradient(90deg, #f59e0b, #fbbf24); color: white; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; white-space: nowrap; font-weight: bold; }}
        .row-2 {{ font-size: 0.8rem; color: #666; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }}
        .display-id {{ color: #888; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 65%; }}
        .link-btn {{ background: #f1f5f9; color: #0f172a; text-decoration: none; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 500; flex-shrink: 0; }}
        .row-3 {{ display: flex; gap: 8px; font-size: 0.75rem; flex-wrap: wrap; }}
        .tag {{ background: #f8fafc; color: #475569; padding: 3px 8px; border-radius: 6px; border: 1px solid #e2e8f0; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header-card">
        <h2>{title}</h2>
        <div class="stats-grid">
            <div class="stat-item"><div class="stat-level">20级</div><div class="stat-count">{level_counts[20]}</div></div>
            <div class="stat-item"><div class="stat-level">19级</div><div class="stat-count">{level_counts[19]}</div></div>
            <div class="stat-item"><div class="stat-level">18级</div><div class="stat-count">{level_counts[18]}</div></div>
            <div class="stat-item"><div class="stat-level">17级</div><div class="stat-count">{level_counts[17]}</div></div>
            <div class="stat-item"><div class="stat-level">16级</div><div class="stat-count">{level_counts[16]}</div></div>
        </div>
    </div>
    <div class="user-list">
        {cards_html}
    </div>
</div>
</body>
</html>
"""

# ==========================================
# 2. 异步爬取任务 (解耦版：只负责更新数据库)
# ==========================================
async def fetch_douyin_fans_task(task_id: str):
    redis = get_redis()
    pool = get_db()
    
    async def update_progress(msg: str):
        logger.info(f"[{task_id}] {msg}")
        # 🌟 修复 1：去掉了 ensure_ascii=False
        await redis.setex(f"scan_task:{task_id}", 3600, json.dumps({
            "status": "processing",
            "message": msg
        }).decode('utf-8'))

    try:
        # 🌟 修复 2：把第一次状态更新移入 try 块内，这样哪怕报错也能被捕捉到
        await update_progress("🚀 雷达扫描任务启动，正在读取有效 Cookie...")

        async with pool.acquire() as conn:
            cookie_record = await conn.fetchrow(
                "SELECT cookie FROM settings_cookies WHERE status = 'valid' ORDER BY updated_at DESC LIMIT 1"
            )
        if not cookie_record or not cookie_record["cookie"]:
            logger.error(f"[{task_id}] ❌ 扫描中止: 数据库中无有效 Cookie")
            # 🌟 修复 3：去掉了所有的 ensure_ascii=False
            await redis.setex(f"scan_task:{task_id}", 3600, json.dumps({"status": "failed", "message": "无有效 Cookie，请先在系统录入"}).decode('utf-8'))
            return
        cookie_str = cookie_record["cookie"]
        
        url = "https://live.douyin.com/webcast/fansclub/club_user_list/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            "Cookie": cookie_str,
            "Referer": "https://live.douyin.com/615189692839?anchor_id="
        }
        base_params = {
            "aid": "6383", "app_name": "douyin_web", "live_id": "1", "device_platform": "web",
            "room_id": "7620063965104491302", "sec_anchor_id": "MS4wLjABAAAA58AFQVygQ3MfiCpOXp-RTUqdyHY-oVSJQHsyWhg4S78",
            "count": "20"
        }

        collected_users = []
        stop_offset = [float('inf')]
        
        async def fetch_single_offset(session, offset):
            for attempt in range(1, 6):
                if offset > stop_offset[0]: return
                params = base_params.copy()
                params["offset"] = offset
                await update_progress(f"正在探测深网数据，当前扫描游标: {offset}...")
                try:
                    async with session.get(url, headers=headers, params=params, timeout=10) as response:
                        response.raise_for_status()
                        json_data = await response.json()
                        
                    user_list = json_data.get("data", {}).get("club_user_list", [])
                    if not user_list:
                        await asyncio.sleep(1 * attempt)
                        continue
                    
                    needs_retry = False
                    for item in user_list:
                        check_ui = item.get("user_info", {})
                        if "***" in check_ui.get("nickname", "") and "111111" in check_ui.get("display_id", ""):
                            needs_retry = True
                            break
                            
                    if needs_retry:
                        await update_progress(f"⚠️ 游标 {offset} 触发掩码风控拦截，正在进行第 {attempt} 次伪装重试...")
                        await asyncio.sleep(2 * attempt)
                        continue

                    for item in user_list:
                        fansclub_info = item.get("user_fansclub_info", {})
                        user_info = item.get("user_info", {})
                        fans_level = fansclub_info.get("level", 0)
                        
                        if 16 <= fans_level <= 20:
                            user_id = user_info.get("id_str", "")
                            if not user_id: continue
                            avatar_url = ""
                            url_list = user_info.get("avatar_thumb", {}).get("url_list", [])
                            if url_list: avatar_url = url_list[0]

                            collected_users.append({
                                "user_id": user_id, "sec_uid": user_info.get("sec_uid", ""),
                                "display_id": user_info.get("display_id", ""), "nickname": user_info.get("nickname", "未知"),
                                "avatar_url": avatar_url, "club_level": fans_level,
                                "intimacy": fansclub_info.get("intimacy", 0), "participate_time": fansclub_info.get("participate_time", 0),
                                "pay_grade": 0
                            })
                        elif fans_level <= 15:
                            if offset < stop_offset[0]:
                                stop_offset[0] = offset
                                await update_progress(f"🛑 触碰 15 级低价值水位线 (游标 {offset})，准备停止外围探测...")
                            break 
                    return
                except Exception as e:
                    logger.debug(f"[{task_id}] 网络异常 offset={offset}: {e}")
                    await asyncio.sleep(2 * attempt)
                    continue

        concurrency = 10
        current_offset = 0
        connector = aiohttp.TCPConnector(limit=concurrency)
        async with aiohttp.ClientSession(connector=connector) as session:
            while current_offset <= stop_offset[0]:
                tasks = []
                for i in range(concurrency):
                    if current_offset > stop_offset[0]: break
                    tasks.append(asyncio.create_task(fetch_single_offset(session, current_offset)))
                    current_offset += 20
                if tasks:
                    await asyncio.gather(*tasks)

        await update_progress(f"✅ 网络扫描结束，共捕获 {len(collected_users)} 个活跃高等级用户。正在执行数据脱水入库...")

        if not collected_users:
            # 🌟 修复 3
            await redis.setex(f"scan_task:{task_id}", 3600, json.dumps({"status": "completed", "message": "无符合条件用户"}).decode('utf-8'))
            return

        upsert_sql = """
            INSERT INTO high_level_fans (
                user_id, sec_uid, display_id, nickname, avatar_url, 
                club_level, intimacy, participate_time, pay_grade
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (user_id) DO UPDATE SET
                nickname = EXCLUDED.nickname,
                club_level = EXCLUDED.club_level,
                intimacy = EXCLUDED.intimacy,
                avatar_url = COALESCE(EXCLUDED.avatar_url, high_level_fans.avatar_url),
                display_id = COALESCE(EXCLUDED.display_id, high_level_fans.display_id),
                updated_at = CURRENT_TIMESTAMP
        """
        
        args = [
            (f["user_id"], f["sec_uid"], f["display_id"], f["nickname"], f["avatar_url"], 
             f["club_level"], f["intimacy"], f["participate_time"], f["pay_grade"])
            for f in collected_users
        ]

        async with pool.acquire() as conn:
            await conn.executemany(upsert_sql, args)
            logger.info(f"[{task_id}] 💾 数据库同步完成: 已更新老粉信息并写入新粉。")
            
        # 🌟 修复 3
        await redis.setex(f"scan_task:{task_id}", 3600, json.dumps({
            "status": "completed", 
            "message": "扫描与数据同步完成"
        }).decode('utf-8'))

    except Exception as e:
        logger.error(f"[{task_id}] 💥 扫描任务崩溃: {str(e)}")
        # 🌟 修复 3
        await redis.setex(f"scan_task:{task_id}", 3600, json.dumps({"status": "failed", "message": str(e)}).decode('utf-8'))

# ==========================================
# 3. 开放 API 接口
# ==========================================

@router.post("/api/tools/high-level/scan/start")
async def start_scan_task(background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    redis = get_redis()
    
    await redis.setex(f"scan_task:{task_id}", 3600, json.dumps({"status": "processing"}).decode('utf-8'))
    background_tasks.add_task(fetch_douyin_fans_task, task_id)
    return {"task_id": task_id, "message": "扫描任务已启动"}

@router.get("/api/tools/high-level/scan/status", response_model=ScanStatusResponse)
async def get_scan_status(task_id: str):
    redis = get_redis()
    data_str = await redis.get(f"scan_task:{task_id}")
    if not data_str:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return json.loads(data_str)


@router.get("/api/tools/high-level/daily-new")
async def get_daily_new_fans(query_date: str = None):
    """查询指定日期的新增高等级粉丝，默认返回今日"""
    if not query_date:
        parsed_date = date.today()
        query_date = parsed_date.isoformat()
    else:
        # 将前端传来的字符串 '2026-04-22' 转换为 Python 的 date 对象
        parsed_date = date.fromisoformat(query_date)
        
    pool = get_db()
    
    sql = """
        SELECT * FROM high_level_fans 
        WHERE DATE(recorded_at) = $1::DATE 
        ORDER BY club_level DESC, intimacy DESC
    """
    
    async with pool.acquire() as conn:
        # ⚠️ 注意这里：必须传入 parsed_date (date对象) 而不是 query_date (字符串)
        records = await conn.fetch(sql, parsed_date)
        
    new_fans = [dict(r) for r in records]
    for fan in new_fans:
        fan["recorded_at"] = fan["recorded_at"].isoformat() if fan.get("recorded_at") else ""
        fan["updated_at"] = fan["updated_at"].isoformat() if fan.get("updated_at") else ""

    return {"date": query_date, "count": len(new_fans), "data": new_fans}
@router.post("/api/tools/high-level/export-new")
async def export_and_save_new_fans(payload: ExportNewRequest):
    if not payload.user_ids:
        raise HTTPException(status_code=400, detail="没有选择任何用户")

    pool = get_db()
    
    # 核心：使用 Postgres 的 ANY($1::text[]) 语法，一次性查出所有被勾选的粉丝数据
    sql = """
        SELECT * FROM high_level_fans 
        WHERE user_id = ANY($1::text[])
        ORDER BY club_level DESC, intimacy DESC
    """
    
    async with pool.acquire() as conn:
        records = await conn.fetch(sql, payload.user_ids)
        
    if not records:
        raise HTTPException(status_code=404, detail="数据库中未找到对应的用户数据")
        
    fans_list = [dict(r) for r in records]

    # 生成 HTML 并导出
    current_date = datetime.now().strftime("%m月%d日")
    filename = f"{current_date}新增16级{len(fans_list)}位.html"
    
    # 渲染模板
    html_content = render_fans_html(fans_list, title=f"陈泽新增高等级粉丝 ({current_date})")

    filename_encoded = urllib.parse.quote(filename)
    return HTMLResponse(
        content=html_content,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"}
    )
@router.get("/api/tools/high-level/export-all")
async def export_all_fans():
    pool = get_db()
    async with pool.acquire() as conn:
        records = await conn.fetch("SELECT * FROM high_level_fans ORDER BY intimacy DESC")
    
    fans_list = [dict(r) for r in records]
    
    filename = f"高等级粉丝全量备份_总计{len(fans_list)}位.html"
    html_content = render_fans_html(fans_list, title="陈泽高等级粉丝团全量档案")

    filename_encoded = urllib.parse.quote(filename)
    return HTMLResponse(
        content=html_content,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"}
    )