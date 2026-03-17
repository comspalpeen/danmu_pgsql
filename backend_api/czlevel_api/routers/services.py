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

# ⚙️ 业务配置
ENABLE_ZERO_LEVEL_SHIELD = True   # 🛡️ 零级防刷拦截
ACTIVE_SHIELD_DAYS = 3            # 🛡️ 活跃粉丝升级缓冲盾 (1-10级)
API_QUERY_LIMIT = 600             # 🚦 单 IP 每小时最多触发外网 API 查询次数
API_QUERY_WINDOW = 3600           # 🚦 限流窗口期 (秒)

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

# 🔧 IP 提取工具
def extract_client_ip(request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    client_ip = forwarded_for.split(",")[0] if forwarded_for else request.client.host
    return client_ip or "unknown_ip"

# 🚦 外部 API 配额限流
async def consume_api_quota(client_ip: str, redis) -> bool:
    if not redis:
        return True
    cache_key = f"rate_limit:api_quota:{client_ip}"
    try:
        current_requests = await redis.incr(cache_key)
        if current_requests == 1:
            await redis.expire(cache_key, API_QUERY_WINDOW)
        if current_requests > API_QUERY_LIMIT:
            return False
    except Exception as e:
        logger.error(f"❌ API 限流器异常: {e}")
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
    """向 users + cz_fans 做 UPSERT，修复了此前的参数缺失异常"""
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

# 🛡️ 业务防刷盾评估
def evaluate_business_shields(user_record, query_str: str, target_sec_uid: str, target_display_id: str):
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
    if ENABLE_ZERO_LEVEL_SHIELD and raw_level == 0:
        return {**base_resp, "source": "database_zero_blocked"}

    last_active = user_record.get('last_active_time')
    if (
        ACTIVE_SHIELD_DAYS > 0
        and 0 < raw_level <= 10
        and last_active
        and (datetime.now() - last_active).days < ACTIVE_SHIELD_DAYS
    ):
        return {**base_resp, "source": "database_recent_blocked"}

    return None
    
# 🗝️ Redis 开关 & 缓存
async def get_api_switch(redis) -> bytes:
    if not redis: return b"1"
    try:
        stored_val = await redis.get("setting:czlevel_api_switch")
        if stored_val is not None: return stored_val
    except Exception: pass
    return b"1"

async def cache_czlevel_result(redis, final_res: dict, latest_data: dict, target_sec_uid: str, target_display_id: str):
    """优化了序列化性能，复用 bytes 载荷直接打入双端 ID"""
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