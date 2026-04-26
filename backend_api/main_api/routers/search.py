# 文件位置: api/routers/search.py
from fastapi import APIRouter, Query
from typing import List
from backend_api.common.database import get_db
from backend_api.common.models import GlobalSearchResult
from backend_api.common.utils import build_avatar_url, build_grade_icon, build_fans_icon, build_gift_icon

router = APIRouter(tags=["search"])

@router.get("/api/search")
async def search_site(q: str = Query(..., min_length=1), limit: int = 20):
    pool = get_db()
    sql = "SELECT * FROM authors WHERE nickname ILIKE $1 OR common_name ILIKE $1 OR sec_uid = $2 ORDER BY weight DESC, follower_count DESC LIMIT $3"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, f"%{q}%", q, limit)
        res = []
        for r in rows:
            d = dict(r)
            d["avatar"] = build_avatar_url(d.get("avatar"))
            res.append(d)
        return res
@router.get("/api/search/users")
async def search_users_prefix(q: str = Query(..., min_length=1), limit: int = 10):
    pool = get_db()
    
    if q.startswith("MS4wLjABAAA"):
        sql = """
            SELECT user_name, sec_uid, avatar_url, pay_grade 
            FROM users 
            WHERE sec_uid = $1
            ORDER BY pay_grade DESC, updated_at DESC LIMIT $2
        """
        args = (q, limit)
    else:
        sql = """
            SELECT user_name, sec_uid, avatar_url, pay_grade 
            FROM users 
            WHERE LOWER(user_name) LIKE $1 AND sec_uid IS NOT NULL AND sec_uid != ''
            ORDER BY pay_grade DESC, updated_at DESC LIMIT $2
        """
        args = (f"{q.lower()}%", limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
        res = []
        for r in rows:
            d = dict(r)
            d["avatar_url"] = build_avatar_url(d.get("avatar_url"))
            res.append(d)
        return res
@router.get("/api/search/global", response_model=List[GlobalSearchResult])
async def search_global_data(
    keyword: str, 
    search_type: str = Query("chat"), 
    limit: int = 20, 
    page: int = 1
): 
    pool = get_db()
    keyword = keyword.strip() if keyword else ""
    
    if not keyword or not keyword.startswith("MS4wLjABAAA"):
        return []
        
    skip = (page - 1) * limit
    
    conditions = ["u.sec_uid = $1"]
    args = [keyword, limit, skip]

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
            LEFT JOIN users u ON c.user_id = u.user_id
            LEFT JOIN rooms r ON c.room_id = r.room_id
            WHERE {where_clause}
            ORDER BY c.created_at DESC
            LIMIT $2 OFFSET $3
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
            LEFT JOIN users u ON c.user_id = u.user_id
            LEFT JOIN rooms r ON c.room_id = r.room_id
            WHERE {where_clause}
            ORDER BY c.created_at DESC
            LIMIT $2 OFFSET $3
        """

    async with pool.acquire() as conn:
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