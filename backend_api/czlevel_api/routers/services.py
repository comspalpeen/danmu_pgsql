# 文件位置: backend_api/czlevel_api/routers/services.py
import aiohttp
import logging
import re
import asyncio
import orjson as json
from datetime import datetime

from backend_api.common.database import get_redis
from backend_api.common.user_agents import get_random_ua
from backend_api.common.utils import build_avatar_url, get_ttwid

logger = logging.getLogger("CzLevelService")


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

# （⚠️ 原先在此处的 4 个常量配置已删除，改为从 Redis 动态获取）

UPSERT_USERS_SQL = """
    INSERT INTO users (user_id, sec_uid, display_id, user_name, gender, pay_grade, avatar_url)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT (user_id) DO UPDATE SET
        sec_uid      = CASE WHEN EXCLUDED.sec_uid != '' THEN EXCLUDED.sec_uid ELSE users.sec_uid END,
        display_id   = CASE WHEN EXCLUDED.display_id != '' THEN EXCLUDED.display_id ELSE users.display_id END,
        user_name    = EXCLUDED.user_name,
        gender       = EXCLUDED.gender,
        pay_grade    = GREATEST(users.pay_grade, EXCLUDED.pay_grade),
        avatar_url   = EXCLUDED.avatar_url,
        updated_at   = CURRENT_TIMESTAMP;
"""

UPSERT_CZFANS_SQL = """
    INSERT INTO cz_fans (user_id, cz_club_level, last_active_time)
    VALUES ($1, $2, CURRENT_TIMESTAMP)
    ON CONFLICT (user_id) DO UPDATE SET
        cz_club_level    = GREATEST(cz_fans.cz_club_level, EXCLUDED.cz_club_level),
        last_active_time = CURRENT_TIMESTAMP;
"""

# 🗝️ 从 Redis 一次性获取所有动态配置 (带默认值兜底)
async def get_dynamic_settings(redis) -> dict:
    settings = {
        "api_switch": 1,
        "enable_zero_level_shield": True,
        "active_shield_days": 3,
        "api_query_limit": 600,
        "api_query_window": 3600,
        "global_api_query_limit": 20000,
    }
    if not redis: 
        return settings
        
    try:
        # 使用 pipeline 提升性能
        pipe = redis.pipeline()
        pipe.get("setting:czlevel_api_switch")
        pipe.get("setting:enable_zero_level_shield")
        pipe.get("setting:active_shield_days")
        pipe.get("setting:api_query_limit")
        pipe.get("setting:api_query_window")
        pipe.get("setting:global_api_query_limit")
        results = await pipe.execute()
        
        settings["api_switch"] = _to_int(results[0], settings["api_switch"])
        settings["enable_zero_level_shield"] = _to_bool(
            results[1],
            settings["enable_zero_level_shield"],
        )
        settings["active_shield_days"] = _to_int(results[2], settings["active_shield_days"])
        settings["api_query_limit"] = _to_int(results[3], settings["api_query_limit"])
        settings["api_query_window"] = _to_int(results[4], settings["api_query_window"])
        settings["global_api_query_limit"] = _to_int(
            results[5],
            settings["global_api_query_limit"],
        )
    except Exception as e:
        logger.error(f"❌ 读取动态配置异常: {e}")
        
    return settings

# 🔧 IP 提取工具
def extract_client_ip(request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    client_ip = forwarded_for.split(",")[0] if forwarded_for else request.client.host
    return client_ip or "unknown_ip"

# 🚦 外部 API 配额限流 (接入动态参数)
async def consume_api_quota(client_ip: str, redis, limit: int, window: int) -> bool:
    if not redis:
        return True
    cache_key = f"rate_limit:api_quota:{client_ip}"
    try:
        current_requests = await redis.incr(cache_key)
        if current_requests == 1:
            await redis.expire(cache_key, window)
        if current_requests > limit:
            return False
    except Exception as e:
        logger.error(f"❌ API 限流器异常: {e}")
    return True

async def consume_global_api_quota(redis, limit: int, window: int) -> bool:
    if not redis:
        return True
    cache_key = "rate_limit:global_api_quota"
    try:
        current_requests = await redis.incr(cache_key)
        if current_requests == 1:
            await redis.expire(cache_key, window)
        if current_requests > limit:
            return False
    except Exception as e:
        logger.error(f"❌ 全局 API 限流器异常: {e}")
    return True

# 查询目标解析
def parse_query_target(query_str: str):
    sec_uid_match = re.search(r'(?:user/|sec_uid=)?(MS4wLjABAAAA[A-Za-z0-9_\-]+)', query_str)
    target_sec_uid = sec_uid_match.group(1) if sec_uid_match else None
    target_display_id = None if target_sec_uid else query_str
    return target_sec_uid, target_display_id

# 🗄️ 数据库查询与写入
async def fetch_user_record_from_db(pool, target_sec_uid=None, target_display_id=None):
    async with pool.acquire() as conn:
        sql = """
            SELECT u.user_id, u.sec_uid, u.display_id, u.user_name, u.avatar_url,
                   f.cz_club_level AS raw_cz_level, f.last_active_time
            FROM users u LEFT JOIN cz_fans f ON u.user_id = f.user_id
        """
        if target_sec_uid:
            return await conn.fetchrow(f"{sql} WHERE u.sec_uid = $1 LIMIT 1", target_sec_uid)
        if target_display_id:
            return await conn.fetchrow(f"{sql} WHERE u.display_id = $1 LIMIT 1", target_display_id)
    return None

async def fetch_users_batch_from_db(pool, sec_uids: list, display_ids: list) -> dict:
    db_records = {}
    if not sec_uids and not display_ids:
        return db_records
    async with pool.acquire() as conn:
        query = """
            SELECT u.user_id, u.sec_uid, u.display_id, u.user_name, u.avatar_url, f.cz_club_level AS raw_cz_level
            FROM users u LEFT JOIN cz_fans f ON u.user_id = f.user_id
            WHERE u.sec_uid = ANY($1::text[]) OR u.display_id = ANY($2::text[])
        """
        rows = await conn.fetch(query, sec_uids, display_ids)
        for r in rows:
            if r['sec_uid']:    db_records[r['sec_uid']]    = dict(r)
            if r['display_id']: db_records[r['display_id']] = dict(r)
    return db_records

async def update_display_id_in_db(pool, display_id: str, sec_uid: str):
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET display_id = $1, updated_at = CURRENT_TIMESTAMP "
                "WHERE sec_uid = $2 AND (display_id IS NULL OR display_id = '')",
                display_id, sec_uid
            )
    except Exception as e:
        logger.error(f"❌ 更新 display_id 失败 [{sec_uid}]: {e}")

async def upsert_user_data(pool, latest_data: dict, target_display_id: str):
    if not latest_data.get('display_id') and target_display_id:
        latest_data['display_id'] = target_display_id
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    UPSERT_USERS_SQL, 
                    latest_data['user_id'], 
                    latest_data.get('sec_uid', ''), 
                    latest_data.get('display_id', ''),
                    latest_data.get('user_name', '未知用户'), 
                    latest_data.get('gender', 0), 
                    latest_data.get('pay_grade', 0),
                    latest_data.get('avatar_url', '')
                )
                await conn.execute(
                    UPSERT_CZFANS_SQL, 
                    latest_data['user_id'], 
                    latest_data.get('cz_club_level', 0)
                )
    except Exception as e:
        logger.error(f"❌ UPSERT 用户数据失败: {e}")

# 外部 API 调用
async def fetch_sec_uid(session: aiohttp.ClientSession, display_id: str) -> str:
    redis = await get_redis()
    cache_key = f"map:did2sec:{display_id}"
    if redis:
        try:
            cached_val = await redis.get(cache_key)
            if cached_val: return cached_val.decode() if isinstance(cached_val, bytes) else cached_val
        except Exception: pass

    url = f"https://www.iesdouyin.com/web/api/v2/user/info/?unique_id={display_id}"
    try:
        async with session.get(url, headers={"User-Agent": get_random_ua()}, timeout=5) as resp:
            if resp.status == 200:
                sec_uid = (await resp.json()).get("user_info", {}).get("sec_uid", "")
                if sec_uid and redis:
                    try: await redis.setex(cache_key, 604800, sec_uid)
                    except Exception: pass
                return sec_uid
    except Exception as e:
        logger.error(f"❌ 获取 sec_uid 失败 [{display_id}]: {e}")
    return ""

async def fetch_live_profile(session: aiohttp.ClientSession, sec_uid: str, ttwid: str) -> dict:
    url = (
        f"https://live.douyin.com/webcast/user/profile/?aid=6383&app_name=douyin_web"
        f"&live_id=1&device_platform=web&language=zh-CN&sec_target_uid={sec_uid}"
        f"&anchor_id=63871524957"
        f"&sec_anchor_id=MS4wLjABAAAA58AFQVygQ3MfiCpOXp-RTUqdyHY-oVSJQHsyWhg4S78"
        f"&current_room_id=7613431014626822954"
    )
    try:
        async with session.get(url, headers={"User-Agent": get_random_ua(), "Cookie": f"ttwid={ttwid};"}, timeout=5) as resp:
            if resp.status == 200:
                profile = (await resp.json()).get("data", {}).get("user_profile", {})
                if profile:
                    b_info = profile.get("base_info", {})
                    avatar_thumb = b_info.get("avatar_thumb", {})
                    raw_uri = avatar_thumb.get("uri", "") if isinstance(avatar_thumb, dict) else ""
                    avatar_uri = raw_uri.split("/")[-1] if "/" in raw_uri else raw_uri
                    return {
                        "user_id":      str(b_info.get("id", "")),
                        "sec_uid":      b_info.get("sec_uid", ""),
                        "display_id":   b_info.get("display_id", ""),
                        "user_name":    b_info.get("nickname", "未知用户"),
                        "gender":       b_info.get("gender", 0),
                        "avatar_url":   avatar_uri,
                        "cz_club_level": profile.get("fans_club", {}).get("data", {}).get("level", 0),
                    }
    except Exception as e:
        logger.error(f"❌ 获取 Profile 失败 [{sec_uid}]: {e}")
    return {}

# 🛡️ 业务防刷盾评估 (接入动态参数)
def evaluate_business_shields(user_record, query_str: str, target_sec_uid: str, target_display_id: str, enable_zero_shield: bool, active_shield_days: int):
    if not user_record or user_record.get('raw_cz_level') is None:
        return None

    raw_level = user_record['raw_cz_level']
    base_resp = {
        "sec_uid":    user_record['sec_uid'],
        "display_id": user_record['display_id'] or target_display_id or query_str,
        "nickname":   user_record['user_name'] or "未知用户",
        "avatar":     build_avatar_url(user_record['avatar_url']),
        "level":      raw_level,
        "passed":     raw_level >= 12,
    }

    if raw_level >= 12:
        return {**base_resp, "source": "database"}
    if enable_zero_shield and raw_level == 0:
        return {**base_resp, "source": "database_zero_blocked"}

    last_active = user_record.get('last_active_time')
    if (
        active_shield_days > 0
        and 0 < raw_level <= 10
        and last_active
        and (datetime.now() - last_active).days < active_shield_days
    ):
        return {**base_resp, "source": "database_recent_blocked"}

    return None

async def cache_czlevel_result(redis, final_res: dict, latest_data: dict, target_sec_uid: str, target_display_id: str):
    if not redis or final_res["level"] >= 12:
        return
    cache_data = {**final_res, "source": "redis_cache"}
    expire = 604800 if final_res["level"] < 11 else 1800
    try:
        pipe = redis.pipeline()
        cache_payload = json.dumps(cache_data)
        
        valid_sec_uid = latest_data.get('sec_uid') or target_sec_uid
        if valid_sec_uid:
            pipe.setex(f"czlevel:cache:{valid_sec_uid}", expire, cache_payload)
            
        valid_display_id = latest_data.get('display_id') or target_display_id
        if valid_display_id:
            pipe.setex(f"czlevel:cache:{valid_display_id}", expire, cache_payload)
            
        await pipe.execute()
    except Exception as e:
        logger.error(f"❌ 写入 Redis 缓存失败: {e}")
