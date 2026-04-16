# 文件位置: api/routers/admin.py
from fastapi import APIRouter, HTTPException, Header, Body, Depends, Query
from typing import List
from datetime import datetime
import hashlib
from backend_api.common.database import get_db, get_redis
from backend_api.common.config import ADMIN_SECRET
from backend_api.common.models import QnAItem, SystemSettings

router = APIRouter(tags=["admin"])


def _to_text(value):
    if isinstance(value, bytes):
        return value.decode()
    return value


def _to_int(value, default: int) -> int:
    text = _to_text(value)
    if text in (None, ""):
        return default
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def _to_bool(value, default: bool) -> bool:
    text = _to_text(value)
    if text in (None, ""):
        return default
    if isinstance(text, bool):
        return text
    normalized = str(text).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default

def verify_admin(x_admin_token: str = Header(..., alias="x-admin-token")):
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="无权访问")

@router.get("/api/qna", response_model=List[QnAItem])
async def get_qna_list(visible_only: bool = True):
    pool = get_db()
    sql = 'SELECT * FROM site_qna WHERE is_visible = TRUE ORDER BY "order" DESC' if visible_only else 'SELECT * FROM site_qna ORDER BY "order" DESC'
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
        res = []
        for r in rows:
            d = dict(r)
            d["id"] = str(d["id"])
            res.append(d)
        return res

@router.post("/api/qna")
async def save_qna(item: QnAItem):
    pool = get_db()
    async with pool.acquire() as conn:
        if item.id:
            await conn.execute('UPDATE site_qna SET question=$1, answer=$2, "order"=$3, is_visible=$4 WHERE id=$5', item.question, item.answer, item.order, item.is_visible, int(item.id))
        else:
            await conn.execute('INSERT INTO site_qna (question, answer, "order", is_visible) VALUES ($1, $2, $3, $4)', item.question, item.answer, item.order, item.is_visible)
    return {"status": "ok"}

@router.delete("/api/qna/{qna_id}")
async def delete_qna(qna_id: str):
    pool = get_db()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM site_qna WHERE id = $1", int(qna_id))
    return {"status": "ok"}

@router.get("/api/admin/cookies")
async def admin_get_cookies(token: str = Header(..., alias="x-admin-token")):
    verify_admin(token)
    pool = get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM settings_cookies ORDER BY updated_at DESC")
        return [dict(r) for r in rows]

@router.post("/api/admin/cookies")
async def admin_add_cookie(payload: dict = Body(...), token: str = Header(..., alias="x-admin-token")):
    verify_admin(token)
    pool = get_db()
    cookie = payload.get("cookie", "").strip()
    note = payload.get("note", "").strip()
    original_cookie_hash = payload.get("original_cookie_hash")
    if not cookie or not note:
        return {"status": "error"}

    cookie_hash = hashlib.md5(cookie.encode('utf-8')).hexdigest()

    upsert_sql = """
        INSERT INTO settings_cookies (cookie_hash, cookie, note, status, updated_at) 
        VALUES ($1, $2, $3, 'valid', CURRENT_TIMESTAMP)
        ON CONFLICT (cookie_hash) DO UPDATE SET 
            cookie = EXCLUDED.cookie, 
            note = EXCLUDED.note, 
            status = 'valid', 
            updated_at = CURRENT_TIMESTAMP
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(upsert_sql, cookie_hash, cookie, note)
            if original_cookie_hash and original_cookie_hash != cookie_hash:
                await conn.execute("DELETE FROM settings_cookies WHERE cookie_hash = $1", original_cookie_hash)
    return {"status": "ok"}

@router.delete("/api/admin/cookies")
async def admin_del_cookie(payload: dict = Body(...), token: str = Header(..., alias="x-admin-token")):
    verify_admin(token)
    pool = get_db()
    async with pool.acquire() as conn:
        if payload.get("cookie_hash"):
            await conn.execute("DELETE FROM settings_cookies WHERE cookie_hash = $1", payload["cookie_hash"])
        elif payload.get("cookie"):
            cookie_hash = hashlib.md5(payload["cookie"].encode('utf-8')).hexdigest()
            await conn.execute("DELETE FROM settings_cookies WHERE cookie_hash = $1", cookie_hash)
    return {"status": "ok"}

@router.get("/api/system/cache-stats")
async def get_cache_stats():
    redis = await get_redis()
    if not redis:
        return {"status": "error", "detail": "Redis client not initialized"}
    try:
        chat_len = await redis.llen("buffer:chats")
        gift_len = await redis.llen("buffer:gifts")
        stats_len = await redis.llen("buffer:stats")
        await redis.set("api_last_check", datetime.now().isoformat(), ex=60)
        return {"status": "connected", "buffer_sizes": {"chats": chat_len, "gifts": gift_len, "stats": stats_len}}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
@router.get("/api/admin/settings", dependencies=[Depends(verify_admin)])
async def get_system_settings():
    """获取系统当前所有动态配置"""
    redis = await get_redis()
    if not redis: 
        raise HTTPException(status_code=500, detail="Redis异常")
    
    # 兼容旧版共享配置键，如果新键不存在则回退到旧键
    single_api_switch = await redis.get("setting:single_api_switch")
    batch_api_switch = await redis.get("setting:batch_api_switch")
    legacy_api_switch = await redis.get("setting:czlevel_api_switch")
    shield_enable = await redis.get("setting:enable_zero_level_shield")
    shield_days = await redis.get("setting:active_shield_days")
    single_limit = await redis.get("setting:single_api_query_limit")
    single_window = await redis.get("setting:single_api_query_window")
    single_global_limit = await redis.get("setting:single_global_api_query_limit")
    batch_limit = await redis.get("setting:batch_api_query_limit")
    batch_window = await redis.get("setting:batch_api_query_window")
    batch_global_limit = await redis.get("setting:batch_global_api_query_limit")
    legacy_limit = await redis.get("setting:api_query_limit")
    legacy_window = await redis.get("setting:api_query_window")
    legacy_global_limit = await redis.get("setting:global_api_query_limit")
    
    return {
        "single_api_switch": _to_int(single_api_switch, _to_int(legacy_api_switch, 1)),
        "batch_api_switch": _to_int(batch_api_switch, _to_int(legacy_api_switch, 1)),
        "enable_zero_level_shield": _to_bool(shield_enable, True),
        "active_shield_days": _to_int(shield_days, 3),
        "single_api_query_limit": _to_int(single_limit, _to_int(legacy_limit, 600)),
        "single_api_query_window": _to_int(single_window, _to_int(legacy_window, 3600)),
        "single_global_api_query_limit": _to_int(
            single_global_limit,
            _to_int(legacy_global_limit, 20000),
        ),
        "batch_api_query_limit": _to_int(batch_limit, _to_int(legacy_limit, 600)),
        "batch_api_query_window": _to_int(batch_window, _to_int(legacy_window, 3600)),
        "batch_global_api_query_limit": _to_int(
            batch_global_limit,
            _to_int(legacy_global_limit, 20000),
        ),
    }

@router.post("/api/admin/settings", dependencies=[Depends(verify_admin)])
async def update_system_settings(settings: SystemSettings):
    """前端一键保存更新所有配置"""
    redis = await get_redis()
    if not redis: 
        raise HTTPException(status_code=500, detail="Redis异常")
    
    # 布尔值转成 "1" 或 "0" 存入 Redis，其他转字符串
    await redis.set("setting:single_api_switch", str(settings.single_api_switch))
    await redis.set("setting:batch_api_switch", str(settings.batch_api_switch))
    await redis.set("setting:enable_zero_level_shield", "1" if settings.enable_zero_level_shield else "0")
    await redis.set("setting:active_shield_days", str(settings.active_shield_days))
    await redis.set("setting:single_api_query_limit", str(settings.single_api_query_limit))
    await redis.set("setting:single_api_query_window", str(settings.single_api_query_window))
    await redis.set("setting:single_global_api_query_limit", str(settings.single_global_api_query_limit))
    await redis.set("setting:batch_api_query_limit", str(settings.batch_api_query_limit))
    await redis.set("setting:batch_api_query_window", str(settings.batch_api_query_window))
    await redis.set("setting:batch_global_api_query_limit", str(settings.batch_global_api_query_limit))
    
    return {"message": "系统核心配置已实时更新 ✅"}
