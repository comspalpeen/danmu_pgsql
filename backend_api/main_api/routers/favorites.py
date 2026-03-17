# 文件位置: api/routers/favorites.py
from typing import List
import asyncio
from backend_api.common.database import get_db
from backend_api.common.models import FavoriteStreamer, BatchCheckRequest
from backend_api.main_api.routers.check import searcher
from fastapi import APIRouter, BackgroundTasks
from backend_api.common.utils import build_avatar_url, build_grade_icon

router = APIRouter(tags=["favorites"])

@router.get("/api/favorites", response_model=List[FavoriteStreamer])
async def get_favorites():
    pool = get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM favorite_streamers ORDER BY created_at DESC")
        results = []
        for r in rows:
            d = dict(r)
            d["avatar_url"] = build_avatar_url(d.get("avatar_url"))
            d["grade_icon_url"] = build_grade_icon(d.get("grade_icon_url"))
            results.append(d)
        return results

@router.post("/api/favorites")
async def add_favorite(streamer: FavoriteStreamer):
    pool = get_db()
    sql = """
        INSERT INTO favorite_streamers (sec_uid, nickname, avatar_url, group_name, display_id, grade_icon_url, follower_count)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (sec_uid) DO UPDATE SET
            nickname = EXCLUDED.nickname, avatar_url = EXCLUDED.avatar_url,
            group_name = EXCLUDED.group_name, display_id = EXCLUDED.display_id,
            grade_icon_url = EXCLUDED.grade_icon_url, follower_count = EXCLUDED.follower_count
    """
    async with pool.acquire() as conn:
        await conn.execute(sql, streamer.sec_uid, streamer.nickname, streamer.avatar_url, streamer.group_name, streamer.display_id, streamer.grade_icon_url, streamer.follower_count)
    return {"status": "ok", "msg": "已收藏"}

@router.delete("/api/favorites/{sec_uid}")
async def delete_favorite(sec_uid: str):
    pool = get_db()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM favorite_streamers WHERE sec_uid = $1", sec_uid)
    return {"status": "ok", "msg": "已删除"}

# 下面的 check_relation 逻辑完全不需要变，保留原样
@router.post("/api/check/batch_relation")
async def batch_check_relation(req: BatchCheckRequest):
    if not req.user_sec_uid or not req.streamer_sec_uids: return []
    sem = asyncio.Semaphore(5)
    async def bounded_check(s_sec):
        async with sem:
            res = await searcher.get_room_relation(req.user_sec_uid, s_sec)
            if res.get("error"):
                return {"target_sec_uid": s_sec, "fans_level": 0, "is_member": False, "is_admin": False, "error": res.get("error")}
            res['target_sec_uid'] = s_sec
            return res
    tasks = [bounded_check(s_sec) for s_sec in req.streamer_sec_uids]
    return await asyncio.gather(*tasks)

@router.post("/api/favorites/refresh_all")
async def refresh_all_favorites(background_tasks: BackgroundTasks):
    pool = get_db()
    async with pool.acquire() as conn:
        streamers = await conn.fetch("SELECT sec_uid, nickname FROM favorite_streamers")
        
    async def process_updates():
        sem = asyncio.Semaphore(5)
        async def update_one(s):
            async with sem:
                profile = await searcher.get_profile(s["sec_uid"])
                if not profile.get("error"):
                    sql = """UPDATE favorite_streamers SET nickname=$1, avatar_url=$2, display_id=$3, grade_icon_url=$4, follower_count=$5 WHERE sec_uid=$6"""
                    async with pool.acquire() as conn:
                        await conn.execute(sql, profile.get("nickname"), profile.get("avatar_url"), profile.get("display_id"), profile.get("grade_icon_url"), profile.get("follower_count", 0), s["sec_uid"])
        tasks = [update_one(dict(s)) for s in streamers]
        await asyncio.gather(*tasks)

    background_tasks.add_task(process_updates)
    return {"status": "ok", "msg": "正在后台更新，请稍后刷新"}