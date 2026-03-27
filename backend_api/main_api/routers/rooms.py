# 文件位置: api/routers/rooms.py
from fastapi import APIRouter, Query
from typing import List
from datetime import datetime
import orjson as json
from backend_api.common.database import get_db
from backend_api.common.models import PkBattle
from backend_api.common.utils import build_avatar_url, build_grade_icon, build_fans_icon, build_gift_icon

router = APIRouter(tags=["rooms"])

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
            
            loops = 0
            while isinstance(teams_data, str) and loops < 3:
                try:
                    teams_data = json.loads(teams_data)
                    loops += 1
                except Exception:
                    break
                    
            if not isinstance(teams_data, list):
                teams_data = []
                
            valid_teams = []
            for t in teams_data:
                if isinstance(t, dict):
                    if "anchors" not in t or t["anchors"] is None:
                        t["anchors"] = []
                    valid_teams.append(t)
            
            if len(valid_teams) == 0:
                valid_teams = [
                    {"team_id": "dummy1", "win_status": 0, "anchors": []},
                    {"team_id": "dummy2", "win_status": 0, "anchors": []}
                ]
            elif len(valid_teams) == 1:
                valid_teams.append({"team_id": "dummy2", "win_status": 0, "anchors": []})
                
            d["teams"] = valid_teams
            
            if d.get("duration") is not None:
                try:
                    d["duration"] = int(d["duration"])
                except:
                    d["duration"] = 0
            else:
                d["duration"] = 0
                
            res.append(d)
            
        return res