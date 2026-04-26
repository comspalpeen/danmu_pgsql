# 文件位置: api/routers/authors.py
from fastapi import APIRouter, Query
from typing import List
import aiohttp
from backend_api.common.database import get_db, get_redis
from backend_api.common.models import Author, RoomSchema, GlobalSearchResult
from backend_api.common.utils import build_avatar_url, build_grade_icon, build_fans_icon, build_gift_icon

router = APIRouter(tags=["authors"])

@router.get("/api/authors", response_model=List[Author])
async def get_authors():
    pool = get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM authors ORDER BY weight ASC, user_count DESC, follower_count DESC")
        res = []
        for r in rows:
            d = dict(r)
            d["avatar"] = build_avatar_url(d.get("avatar"))
            res.append(d)
        return res

@router.get("/api/authors/{sec_uid}/rooms", response_model=List[RoomSchema])
async def get_author_rooms(sec_uid: str, limit: int = 0):
    pool = get_db()
    async with pool.acquire() as conn:
        uid_row = await conn.fetchrow("SELECT user_id FROM users WHERE sec_uid = $1", sec_uid)
        

        sql = "SELECT * FROM rooms WHERE user_id = $1 ORDER BY created_at DESC"
        args = [uid_row["user_id"]]
            
        if limit > 0: sql += f" LIMIT {limit}"
        
        rows = await conn.fetch(sql, *args)
        res = []
        for r in rows:
            d = dict(r)
            d["cover_url"] = build_avatar_url(d.get("avatar_url"))
            res.append(d)
        return res

@router.get("/api/authors/{sec_uid}/chats", response_model=List[GlobalSearchResult])
async def search_author_data(
    sec_uid: str, 
    keyword: str = Query(..., min_length=1), 
    search_type: str = Query("chat"), 
    limit: int = 50, 
    page: int = 1
):
    pool = get_db()
    keyword = keyword.strip() if keyword else ""
    
    if not keyword or not keyword.startswith("MS4wLjABAAA"):
        return []

    skip = (page - 1) * limit
    
    async with pool.acquire() as conn:
        uid_row = await conn.fetchrow("SELECT user_id FROM users WHERE sec_uid = $1", sec_uid)
        author_user_id = uid_row["user_id"] if uid_row and uid_row["user_id"] else None

        conditions = ["u.sec_uid = $1"]
        args = [keyword]
        idx = 2


        conditions.append(f"r.user_id = ${idx}")
        args.append(author_user_id)
        idx += 1

        where_clause = " AND ".join(conditions)
        
        if search_type == "gift":
            sql = f"""
                SELECT c.user_name, c.gift_name as content, c.created_at, c.room_id,
                       c.pay_grade_icon, c.fans_club_icon,
                       c.total_diamond_count, c.gift_icon,
                       (COALESCE(c.combo_count, 1) * COALESCE(c.group_count, 1)) as gift_count,
                       u.sec_uid, u.avatar_url,
                       COALESCE(r.nickname, '未知主播') as anchor_name,
                       COALESCE(r.title, '') as room_title,
                       COALESCE(r.avatar_url, '') as room_cover
                FROM live_gifts c
                INNER JOIN rooms r ON c.room_id = r.room_id
                LEFT JOIN users u ON c.user_id = u.user_id
                WHERE {where_clause}
                ORDER BY c.created_at DESC
                LIMIT ${idx} OFFSET ${idx+1}
            """
        else:
            sql = f"""
                SELECT c.user_name, c.content, c.created_at, c.room_id,
                       c.pay_grade_icon, c.fans_club_icon,
                       0 as total_diamond_count, '' as gift_icon,
                       0 as gift_count,
                       u.sec_uid, u.avatar_url,
                       COALESCE(r.nickname, '未知主播') as anchor_name,
                       COALESCE(r.title, '') as room_title,
                       COALESCE(r.avatar_url, '') as room_cover
                FROM live_chats c
                INNER JOIN rooms r ON c.room_id = r.room_id
                LEFT JOIN users u ON c.user_id = u.user_id
                WHERE {where_clause}
                ORDER BY c.created_at DESC
                LIMIT ${idx} OFFSET ${idx+1}
            """
            
        args.extend([limit, skip])
        rows = await conn.fetch(sql, *args)

    results = []
    for r in rows:
        d = dict(r)
        d["avatar_url"] = build_avatar_url(d.get("avatar_url"))
        d["room_cover"] = build_avatar_url(d.get("room_cover"))
        d["pay_grade_icon"] = build_grade_icon(d.get("pay_grade_icon"))
        d["fans_club_icon"] = build_fans_icon(d.get("fans_club_icon"))
        if search_type == "gift":
            d["gift_icon"] = build_gift_icon(d.get("gift_icon"))
        results.append(d)
        
    return results

@router.get("/api/lookup_user/{target_uid}")
async def lookup_user(target_uid: str):
    redis = await get_redis()
    cache_key = f"user_lookup:{target_uid}"
    if redis:
        try:
            cached_sec_uid = await redis.get(cache_key)
            if cached_sec_uid: return {"sec_uid": cached_sec_uid}
        except: pass
        
    url = "https://live.douyin.com/webcast/user/"
    params = {"aid": "6383", "live_id": "1", "device_platform": "web", "language": "zh-CN", "target_uid": target_uid}
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": "Mozilla/5.0"}
            async with session.get(url, params=params, headers=headers, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sec_uid = data.get("data", {}).get("sec_uid")
                    if sec_uid:
                        if redis:
                            try: await redis.set(cache_key, sec_uid, ex=3600)
                            except: pass
                        return {"sec_uid": sec_uid}
    except: pass
    return {"sec_uid": None}
    
