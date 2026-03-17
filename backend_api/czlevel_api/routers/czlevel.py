# 文件位置: backend_api/czlevel_api/routers/czlevel.py
from fastapi import APIRouter, HTTPException, Query, Depends, Request, Header
import aiohttp
import logging
import orjson as json
import asyncio

from backend_api.common.database import get_redis, get_db
from backend_api.common.utils import build_avatar_url, get_ttwid
from backend_api.common.models import CzLevelBatchRequest
from backend_api.common.config import ADMIN_SECRET
from backend_api.czlevel_api.routers.services import (
    API_QUERY_LIMIT,
    extract_client_ip,
    consume_api_quota,
    parse_query_target,
    get_api_switch,
    fetch_user_record_from_db,
    fetch_users_batch_from_db,
    update_display_id_in_db,
    upsert_user_data,
    evaluate_business_shields,
    fetch_sec_uid,
    fetch_live_profile,
    cache_czlevel_result,
)

logger = logging.getLogger("CzLevelAPI")
router = APIRouter(tags=["czlevel"])

def verify_admin(x_admin_token: str = Header(..., alias="x-admin-token")):
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="无权访问")

@router.post("/api/czlevel/api_switch", dependencies=[Depends(verify_admin)])
async def toggle_api_switch(mode: int = Query(..., description="0:关闭 1:全开 2:仅转换")):
    if mode not in (0, 1, 2): raise HTTPException(status_code=400, detail="模式错误")
    redis = await get_redis()
    if not redis: raise HTTPException(status_code=500, detail="Redis异常")
    await redis.set("setting:czlevel_api_switch", str(mode))
    mode_text = {0: "关闭 🛑", 1: "全开 ✅", 2: "仅转换 ⚠️"}
    return {"message": f"外网查询功能已切换至：{mode_text[mode]}"}

@router.get("/api/czlevel/author")
async def get_cz_author_info():
    pool = get_db()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM authors WHERE sec_uid = 'MS4wLjABAAAA58AFQVygQ3MfiCpOXp-RTUqdyHY-oVSJQHsyWhg4S78' LIMIT 1")
            if not row: return {"error": "未找到陈泽的档案数据"}
            res = dict(row)
            res["avatar"] = build_avatar_url(res.get("avatar"))
            return res
    except Exception as e:
        raise HTTPException(status_code=500, detail="数据库查询异常")

@router.get("/api/czlevel")
async def check_cz_level(request: Request, display_id: str = Query(...)):
    query_str = display_id.strip()
    if not query_str: raise HTTPException(status_code=400, detail="不能为空")

    pool = get_db()
    target_sec_uid, target_display_id = parse_query_target(query_str)

    user_record = None
    try: user_record = await fetch_user_record_from_db(pool, target_sec_uid, target_display_id)
    except Exception as e: logger.error(f"❌ 查库异常: {e}")

    shield_result = evaluate_business_shields(user_record, query_str, target_sec_uid, target_display_id)
    if shield_result: return shield_result

    redis = await get_redis()
    api_switch = await get_api_switch(redis)

    if api_switch == b"0":
        raw_level = user_record['raw_cz_level'] if user_record else None
        return {
            "sec_uid":    user_record['sec_uid'] if user_record else (target_sec_uid or ""),
            "display_id": target_display_id or query_str,
            "nickname":   user_record['user_name'] if user_record else "未知用户",
            "avatar":     build_avatar_url(user_record['avatar_url']) if user_record else "",
            "level":      raw_level if raw_level is not None else 0,
            "source":     "database_only",
            "passed":     False,
        }

    cache_key = f"czlevel:cache:{target_sec_uid or target_display_id}"
    if redis:
        try:
            cached_val = await redis.get(cache_key)
            if cached_val: return json.loads(cached_val)
        except: pass

    async with aiohttp.ClientSession() as session:
        if not target_sec_uid and target_display_id:
            target_sec_uid = await fetch_sec_uid(session, target_display_id)
            if target_sec_uid:
                await update_display_id_in_db(pool, target_display_id, target_sec_uid)
                try:
                    new_record = await fetch_user_record_from_db(pool, target_sec_uid=target_sec_uid)
                    if new_record:
                        user_record = new_record
                        shield_result = evaluate_business_shields(user_record, query_str, target_sec_uid, target_display_id)
                        if shield_result: return shield_result
                except Exception as e: logger.error(f"❌ 转换后复查异常: {e}")

        if not target_sec_uid:
            return {
                "sec_uid": "", "display_id": target_display_id or query_str,
                "nickname": user_record['user_name'] if user_record else "未知用户",
                "avatar": build_avatar_url(user_record['avatar_url']) if user_record else "",
                "level": user_record['raw_cz_level'] if user_record and user_record['raw_cz_level'] is not None else 0,
                "source": "convert_failed", "passed": False
            }

        if api_switch == b"2":
            return {
                "sec_uid": target_sec_uid, "display_id": target_display_id or query_str,
                "nickname": user_record['user_name'] if user_record else "未知用户",
                "avatar": build_avatar_url(user_record['avatar_url']) if user_record else "",
                "level": user_record['raw_cz_level'] if user_record and user_record['raw_cz_level'] is not None else 0,
                "source": "convert_only", "passed": False
            }

        client_ip = extract_client_ip(request)
        can_use_api = await consume_api_quota(client_ip, redis)
        if not can_use_api:
            logger.info(f"⚠️ [{query_str}] IP 触发等级查询降级限流 (>{API_QUERY_LIMIT}次/小时)")
            return {
                "sec_uid": user_record['sec_uid'] if user_record else (target_sec_uid or ""),
                "display_id": target_display_id or query_str,
                "nickname": user_record['user_name'] if user_record else "未知用户",
                "avatar": build_avatar_url(user_record['avatar_url']) if user_record else "",
                "level": user_record['raw_cz_level'] if user_record and user_record['raw_cz_level'] is not None else 0,
                "source": "rate_limit_db_only", "passed": False
            }

        ttwid = await get_ttwid(force_refresh=False)
        latest_data = await fetch_live_profile(session, target_sec_uid, ttwid)
        if not latest_data:
            ttwid = await get_ttwid(force_refresh=True)
            latest_data = await fetch_live_profile(session, target_sec_uid, ttwid)

        api_level     = latest_data.get('cz_club_level', 0)
        history_level = user_record['raw_cz_level'] if user_record and user_record['raw_cz_level'] is not None else 0
        final_level   = max(api_level, history_level)

        if final_level >= 12 and latest_data and latest_data.get('user_id'):
            await upsert_user_data(pool, latest_data, target_display_id)
        elif latest_data and latest_data.get('display_id'):
            await update_display_id_in_db(pool, latest_data['display_id'], target_sec_uid)

        final_res = {
            "sec_uid":    latest_data.get('sec_uid') or target_sec_uid or "",
            "display_id": latest_data.get('display_id') or query_str,
            "nickname":   latest_data.get('user_name', '未知用户'),
            "avatar":     build_avatar_url(latest_data.get('avatar_url', '')),
            "level":      final_level,
            "source":     "api_updated",
            "passed":     final_level >= 12,
        }

        await cache_czlevel_result(redis, final_res, latest_data, target_sec_uid, target_display_id)
        return final_res

@router.post("/api/czlevel/batch")
async def batch_check_cz_level(req: CzLevelBatchRequest):
    targets = [t.strip() for t in req.targets if t.strip()]
    if not targets: raise HTTPException(status_code=400, detail="不能为空")
    if len(targets) > 100: raise HTTPException(status_code=400, detail="单次查询不能超过 100 条")

    parsed_targets, sec_uids_to_query, display_ids_to_query = {}, [], []
    for t in targets:
        target_sec_uid, target_display_id = parse_query_target(t)
        if target_sec_uid:
            parsed_targets[t] = {"type": "sec_uid", "value": target_sec_uid}
            sec_uids_to_query.append(target_sec_uid)
        else:
            parsed_targets[t] = {"type": "display_id", "value": t}
            display_ids_to_query.append(t)

    pool = get_db()
    try: db_records = await fetch_users_batch_from_db(pool, sec_uids_to_query, display_ids_to_query)
    except Exception as e:
        logger.error(f"❌ 批量查库异常: {e}")
        db_records = {}

    redis = await get_redis()
    api_switch = await get_api_switch(redis)

    converted_map = {}
    missing_display_ids = [did for did in display_ids_to_query if did not in db_records]

    if api_switch != b"0" and missing_display_ids:
        async with aiohttp.ClientSession() as session:
            tasks   = [fetch_sec_uid(session, did) for did in missing_display_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_sec_uids = []
            for did, res_sec_uid in zip(missing_display_ids, results):
                if isinstance(res_sec_uid, str) and res_sec_uid.startswith("MS4wLjABAAAA"):
                    converted_map[did] = res_sec_uid
                    new_sec_uids.append(res_sec_uid)

            if new_sec_uids:
                try:
                    extra = await fetch_users_batch_from_db(pool, new_sec_uids, [])
                    db_records.update(extra)

                    update_params = [(did, su) for did, su in converted_map.items() if su in db_records]
                    if update_params:
                        async with pool.acquire() as conn:
                            await conn.executemany("UPDATE users SET display_id = $1, updated_at = CURRENT_TIMESTAMP WHERE sec_uid = $2 AND (display_id IS NULL OR display_id = '')", update_params)
                except Exception: pass

    final_response = []
    base_source = "database_only" if api_switch == b"0" else "database"

    for t in targets:
        item = parsed_targets[t]
        val  = item["value"]
        
        record = db_records.get(val)
        source = base_source

        # 精简逻辑：如果直查未命中，且原本输入的是 display_id，则尝试去转换表中获取关联数据
        if not record and item["type"] == "display_id" and val in converted_map:
            mapped_su = converted_map[val]
            record    = db_records.get(mapped_su)
            source    = "database" if record else "failed_or_not_in_db"
        elif not record:
            source = "not_found"

        if record:
            raw_level = record['raw_cz_level']
            level     = raw_level if raw_level is not None else 0
            final_response.append({
                "query":      t,
                "sec_uid":    record['sec_uid'],
                "display_id": record['display_id'] or (val if item["type"] == "display_id" else ""),
                "nickname":   record['user_name'] or "未知用户",
                "avatar":     build_avatar_url(record['avatar_url']),
                "level":      level,
                "source":     source,
                "passed":     level >= 12,
            })
        else:
            final_response.append({
                "query":      t,
                "sec_uid":    "",
                "display_id": val if item["type"] == "display_id" else "",
                "nickname":   "查无此人",
                "avatar":     "",
                "level":      0,
                "source":     source,
                "passed":     False,
            })

    return {"results": final_response}