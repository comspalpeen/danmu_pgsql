# 文件位置: api/routers/legacy.py
from fastapi import APIRouter, HTTPException, Header, Query, Body
from typing import List
import aiohttp
from datetime import datetime, timedelta
from backend_api.common.database import get_db, get_redis
from backend_api.common.config import ADMIN_SECRET
from backend_api.common.models import Author, RoomSchema, PkBattle, QnAItem, GlobalSearchResult
from backend_api.common.utils import build_avatar_url, build_grade_icon, build_fans_icon, build_gift_icon
import hashlib
import orjson as json
router = APIRouter(tags=["legacy"])

def verify_admin(x_admin_token: str = Header(..., alias="x-admin-token")):
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="无权访问")

@router.get("/api/rooms/{room_id}/detail")
async def get_room_detail(room_id: str):
    pool = get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM rooms WHERE room_id = $1", room_id)
        if not row: return {"error": "Room not found"}
        res = dict(row)
        res["avatar_url"] = build_avatar_url(res.get("avatar_url"))
        return res

@router.get("/api/rooms/{room_id}/gifts")
async def get_room_gifts(
    room_id: str, limit: int = 200, before_time: str = Query(None),
    keyword: str = Query(None), min_price: int = Query(0),
    min_pay_grade: int = Query(0), min_fans_club_level: int = Query(0),
    gender: int = Query(None), start_time: str = Query(None), end_time: str = Query(None)
):
    pool = get_db()
    conditions = ["g.room_id = $1"]
    args = [room_id]
    idx = 2

    if keyword:
        if keyword.startswith("*"):
            conditions.append(f"g.user_name ILIKE ${idx}")
            args.append(f"%{keyword[1:]}%")
        else:
            conditions.append(f"(g.gift_name ILIKE ${idx} OR g.user_name ILIKE ${idx})")
            args.append(f"%{keyword}%")
        idx += 1

    if min_price > 0:
        conditions.append(f"g.total_diamond_count >= ${idx}")
        args.append(min_price)
        idx += 1

    if min_pay_grade > 0:
        conditions.append(f"g.pay_grade >= ${idx}")
        args.append(min_pay_grade)
        idx += 1

    if min_fans_club_level > 0:
        conditions.append(f"g.fans_club_level >= ${idx}")
        args.append(min_fans_club_level)
        idx += 1

    if gender is not None:
        conditions.append(f"u.gender = ${idx}")
        args.append(gender)
        idx += 1

    if start_time:
        conditions.append(f"g.created_at >= ${idx}")
        args.append(datetime.fromisoformat(start_time.replace('Z', '+00:00')).replace(tzinfo=None))
        idx += 1

    if end_time:
        conditions.append(f"g.created_at <= ${idx}")
        args.append(datetime.fromisoformat(end_time.replace('Z', '+00:00')).replace(tzinfo=None))
        idx += 1

    if before_time:
        conditions.append(f"g.created_at < ${idx}")
        args.append(datetime.fromisoformat(before_time.replace('Z', '+00:00')).replace(tzinfo=None))
        idx += 1

    # 核心 SQL: 只关联 sec_uid, avatar_url, gender
    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT g.*, u.sec_uid, u.avatar_url, u.gender
        FROM live_gifts g
        LEFT JOIN users u ON g.user_id = u.user_id
        WHERE {where_clause}
        ORDER BY g.created_at DESC LIMIT ${idx}
    """
    args.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
        
    gifts = []
    for r in rows:
        d = dict(r)
        d["avatar_url"] = build_avatar_url(d.get("avatar_url"))
        d["pay_grade_icon"] = build_grade_icon(d.get("pay_grade_icon"))
        d["fans_club_icon"] = build_fans_icon(d.get("fans_club_icon"))
        d["gift_icon_url"] = build_gift_icon(d.get("gift_icon"))
        gifts.append(d)
    return gifts

@router.get("/api/rooms/{room_id}/chats")
async def get_room_chats(
    room_id: str, limit: int = 200, before_time: str = Query(None), 
    keyword: str = Query(None), min_pay_grade: int = Query(0),
    min_fans_club_level: int = Query(0), gender: int = Query(None),
    start_time: str = Query(None), end_time: str = Query(None)
):
    pool = get_db()
    conditions = ["c.room_id = $1"]
    args = [room_id]
    idx = 2

    if keyword:
        if keyword.startswith("*"):
            conditions.append(f"c.user_name ILIKE ${idx}")
            args.append(f"%{keyword[1:]}%")
        else:
            conditions.append(f"(c.content ILIKE ${idx} OR c.user_name ILIKE ${idx})")
            args.append(f"%{keyword}%")
        idx += 1

    if min_pay_grade > 0:
        conditions.append(f"c.pay_grade >= ${idx}")
        args.append(min_pay_grade)
        idx += 1

    if min_fans_club_level > 0:
        conditions.append(f"c.fans_club_level >= ${idx}")
        args.append(min_fans_club_level)
        idx += 1

    if gender is not None:
        conditions.append(f"u.gender = ${idx}")
        args.append(gender)
        idx += 1

    if start_time:
        conditions.append(f"c.created_at >= ${idx}")
        args.append(datetime.fromisoformat(start_time.replace('Z', '+00:00')).replace(tzinfo=None))
        idx += 1
    if end_time:
        conditions.append(f"c.created_at <= ${idx}")
        args.append(datetime.fromisoformat(end_time.replace('Z', '+00:00')).replace(tzinfo=None))
        idx += 1
    if before_time:
        conditions.append(f"c.created_at < ${idx}")
        args.append(datetime.fromisoformat(before_time.replace('Z', '+00:00')).replace(tzinfo=None))
        idx += 1

    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT c.*, u.sec_uid, u.avatar_url, u.gender
        FROM live_chats c
        LEFT JOIN users u ON c.user_id = u.user_id
        WHERE {where_clause}
        ORDER BY c.created_at DESC LIMIT ${idx}
    """
    args.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
        
    chats = []
    for r in rows:
        d = dict(r)
        d["avatar_url"] = build_avatar_url(d.get("avatar_url"))
        d["pay_grade_icon"] = build_grade_icon(d.get("pay_grade_icon"))
        d["fans_club_icon"] = build_fans_icon(d.get("fans_club_icon"))
        chats.append(d)
    return chats

@router.get("/api/rooms/{room_id}/pks", response_model=List[PkBattle])
async def get_room_pks(room_id: str, limit: int = 20):
    pool = get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM pk_history WHERE room_id = $1 ORDER BY created_at DESC LIMIT $2", room_id, limit)
        res = []
        for r in rows:
            d = dict(r)
            
            teams_data = d.get("teams")
            
            # 1. 暴力循环解包：专门对付存入数据库时被嵌套 dumps 多次的“洋葱字符串”
            loops = 0
            while isinstance(teams_data, str) and loops < 3:
                try:
                    teams_data = json.loads(teams_data)
                    loops += 1
                except Exception:
                    break
                    
            # 2. 如果解包到底，仍然不是 list（或者是 None），则初始化为空列表
            if not isinstance(teams_data, list):
                teams_data = []
                
            # 3. 深度清洗：确保内部的每个 team 都是字典，并且绝不缺少 anchors 字段
            valid_teams = []
            for t in teams_data:
                if isinstance(t, dict):
                    if "anchors" not in t or t["anchors"] is None:
                        t["anchors"] = []
                    valid_teams.append(t)
            
            # 🛡️ 4. 前端保命机制（最关键）：
            # 前端通常强制要求有 PK 双方，如果连队伍都没有，去读 teams[0] 必然白屏。
            # 我们直接给它塞入两个空队伍兜底，确保前端不崩。
            if len(valid_teams) == 0:
                valid_teams = [
                    {"team_id": "dummy1", "win_status": 0, "anchors": []},
                    {"team_id": "dummy2", "win_status": 0, "anchors": []}
                ]
            elif len(valid_teams) == 1:
                # 如果只有单方数据，强行补齐第二方
                valid_teams.append({"team_id": "dummy2", "win_status": 0, "anchors": []})
                
            d["teams"] = valid_teams
            
            # 5. 兼容 duration，防止报错
            if d.get("duration") is not None:
                try:
                    d["duration"] = int(d["duration"])
                except:
                    d["duration"] = 0
            else:
                d["duration"] = 0
                
            res.append(d)
            
        return res

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

@router.get("/api/search/global", response_model=List[GlobalSearchResult])
async def search_global_data(
    keyword: str, 
    search_type: str = Query("chat"), 
    limit: int = 20, 
    page: int = 1
): 
    pool = get_db()
    keyword = keyword.strip() if keyword else ""
    
    # 🚨 核心防御：强制只允许 sec_uid 搜索！杜绝任何对弹幕/礼物大表的模糊扫描！
    if not keyword or not keyword.startswith("MS4wLjABAAA"):
        return []
        
    skip = (page - 1) * limit
    
    # 因为已经限定了精准 UID，直接解除 30 天时间限制
    conditions = ["u.sec_uid = $1"]
    args = [keyword, limit, skip]

    where_clause = " AND ".join(conditions)

    # 🎁 查礼物
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
    # 💬 查弹幕
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
        # 🌟 先查出高轻量级的 user_id
        uid_row = await conn.fetchrow("SELECT user_id FROM users WHERE sec_uid = $1", sec_uid)
        
        if uid_row and uid_row["user_id"]:
            # 如果存在，用 user_id 极速查询
            sql = "SELECT * FROM rooms WHERE user_id = $1 ORDER BY created_at DESC"
            args = [uid_row["user_id"]]
        else:
            # 兼容降级
            sql = "SELECT * FROM rooms WHERE sec_uid = $1 ORDER BY created_at DESC"
            args = [sec_uid]
            
        if limit > 0: sql += f" LIMIT {limit}"
        
        rows = await conn.fetch(sql, *args)
        res = []
        for r in rows:
            d = dict(r)
            d["cover_url"] = build_avatar_url(d.get("avatar_url"))
            res.append(d)
        return res

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
    if not cookie and not note: return {"status": "error"}
    
    # 🌟 核心：计算 MD5 哈希作为主键
    cookie_hash = hashlib.md5(cookie.encode('utf-8')).hexdigest()
    
    sql = """
        INSERT INTO settings_cookies (cookie_hash, cookie, note, status, updated_at) 
        VALUES ($1, $2, $3, 'valid', CURRENT_TIMESTAMP)
        ON CONFLICT (cookie_hash) DO UPDATE SET 
            cookie = EXCLUDED.cookie, 
            note = EXCLUDED.note, 
            status = 'valid',     -- 👇 核心修复：如果是覆盖旧的/失效的，让它满血复活
            updated_at = CURRENT_TIMESTAMP
    """
    async with pool.acquire() as conn:
        await conn.execute(sql, cookie_hash, cookie, note)
    return {"status": "ok"}

@router.delete("/api/admin/cookies")
async def admin_del_cookie(payload: dict = Body(...), token: str = Header(..., alias="x-admin-token")):
    verify_admin(token)
    pool = get_db()
    async with pool.acquire() as conn:
        if payload.get("cookie_hash"):
            # 兼容：如果前端已经知道 hash，直接传 hash 删除
            await conn.execute("DELETE FROM settings_cookies WHERE cookie_hash = $1", payload["cookie_hash"])
        elif payload.get("cookie"):
            # 兼容：如果前端还是传的一大串完整 cookie，我们帮它转成 hash 后再删除
            cookie_hash = hashlib.md5(payload["cookie"].encode('utf-8')).hexdigest()
            await conn.execute("DELETE FROM settings_cookies WHERE cookie_hash = $1", cookie_hash)
        # 移除了原先的 elif payload.get("note") 逻辑，防止误删
    return {"status": "ok"}

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
    
    # 🚨 核心防御：强制只允许 sec_uid 搜索！彻底杜绝房间内的模糊文本扫描！
    if not keyword or not keyword.startswith("MS4wLjABAAA"):
        return []

    skip = (page - 1) * limit
    
    async with pool.acquire() as conn:
        # 1. 尝试从 users 表获取主播的 user_id 进行极速查询
        uid_row = await conn.fetchrow("SELECT user_id FROM users WHERE sec_uid = $1", sec_uid)
        author_user_id = uid_row["user_id"] if uid_row and uid_row["user_id"] else None

        # 2. 基础条件：锁定精确的 UID
        conditions = ["u.sec_uid = $1"]
        args = [keyword]
        idx = 2

        # 3. 附加条件：严格限定在当前主播的房间内
        if author_user_id:
            conditions.append(f"r.user_id = ${idx}")
            args.append(author_user_id)
        else:
            # 兼容老数据降级
            conditions.append(f"r.sec_uid = ${idx}")
            args.append(sec_uid)
        idx += 1

        where_clause = " AND ".join(conditions)
        
        # 4. 核心查询拼装 (解除时间限制)
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
        # 🚀 极致优化：使用 LOWER(user_name) LIKE 配合前端传来的小写关键词
        sql = """
            SELECT user_name, sec_uid, avatar_url, pay_grade 
            FROM users 
            WHERE LOWER(user_name) LIKE $1 AND sec_uid IS NOT NULL AND sec_uid != ''
            ORDER BY pay_grade DESC, updated_at DESC LIMIT $2
        """
        # 👇 核心：把用户输入的 q 转成小写，再拼接 %
        args = (f"{q.lower()}%", limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
        res = []
        for r in rows:
            d = dict(r)
            d["avatar_url"] = build_avatar_url(d.get("avatar_url"))
            res.append(d)
        return res

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
        res = []
        for r in rows:
            d = dict(r)
            d["avatar_url"] = build_avatar_url(d.get("avatar_url"))
            res.append(d)
        return res