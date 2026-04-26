# 文件位置: api/routers/ai_chat.py
from fastapi import APIRouter, Body
from pydantic import BaseModel
from typing import List
from datetime import datetime, timedelta
import orjson as json
import asyncio
import traceback
import re

from backend_api.common.database import get_db
from zai import ZhipuAiClient

router = APIRouter(tags=["ai"])

import os
from dotenv import load_dotenv

# Load .env from the root directory of the project
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), '.env')
load_dotenv(dotenv_path)

# 尊贵的付费版 API Key
API_KEY = os.environ.get("ZHIPU_API_KEY")
if not API_KEY:
    raise ValueError("ZHIPU_API_KEY is not set in the environment variables")
client = ZhipuAiClient(api_key=API_KEY)

# ==========================================
# 🌟 核心引擎 1：实体解析器 (安全防崩溃版 - PG版)
# ==========================================
async def resolve_entities(keyword: str):
    """提取精确的主播列表。支持 'GuildName+AnchorName' 的模糊匹配"""
    try:
        pool = get_db()
        matched_authors = []
        
        keyword_clean = keyword.strip().lower()
        sub_keywords = [k.strip().lower() for k in re.split(r'[和与、,，\s]+', keyword) if k.strip()]
        if not sub_keywords: sub_keywords = [keyword_clean]
        
        async with pool.acquire() as conn:
            # 拿到全部主播数据做 Python 层的智能包含匹配 (更宽容)
            rows = await conn.fetch("SELECT * FROM authors")
            
        for row in rows:
            author = dict(row)
            guild = (author.get("guild") or "").lower()
            nickname = (author.get("nickname") or "").lower()
            c_names_str = (author.get("common_name") or "")
            c_names = [n.strip().lower() for n in c_names_str.replace("，", ",").split(",") if n.strip()]
            
            is_match = False
            for kw in sub_keywords:
                if guild and kw == guild: 
                    is_match = True
                elif kw in nickname or nickname in kw: 
                    is_match = True
                elif any(kw in cn or cn in kw for cn in c_names):
                    is_match = True
            
            if is_match: matched_authors.append(author)
                
        # 去重
        unique_authors = {a["sec_uid"]: a for a in matched_authors}.values()
        return list(unique_authors)
    except Exception as e:
        print(f"⚠️ 实体解析报错: {e}")
        return []

# ==========================================
# 🌟 核心引擎 2：满血版业务工具箱 (原生 PG SQL版)
# ==========================================

def get_current_month_first_day():
    now = datetime.now()
    return datetime(now.year, now.month, 1)

async def tool_daily_fanclub(keyword: str, query_type: str = "latest", target_date: str = ""):
    authors = await resolve_entities(keyword)
    if not authors: return json.dumps({"msg": f"未找到【{keyword}】的主播"}, ensure_ascii=False)
    
    # ⚠️ 注意：daily_reports 表只存了 uid，所以这里提取 uid
    uids = [a["uid"] for a in authors if a.get("uid")]
    if not uids: return json.dumps({"msg": f"【{keyword}】缺少UID信息，无法查询粉丝团"}, ensure_ascii=False)

    pool = get_db()
    first_day = get_current_month_first_day().date()
    results = []
    
    try:
        async with pool.acquire() as conn:
            for uid in uids:
                query = "SELECT * FROM daily_reports WHERE uid = $1 AND date >= $2"
                args = [uid, first_day]
                order_by = "date DESC"
                limit = 1
                
                if query_type == "specific_date" and target_date:
                    try:
                        query = "SELECT * FROM daily_reports WHERE uid = $1 AND date = $2"
                        args = [uid, datetime.strptime(target_date, "%Y-%m-%d").date()]
                    except: pass
                elif query_type == "max_new_fans":
                    order_by = "today_new_fans DESC"
                    limit = 3
                elif query_type == "max_tasks":
                    order_by = "task_1_completed DESC"
                    limit = 3
                elif query_type == "max_active":
                    order_by = "active_fans_count DESC"
                    limit = 3

                sql = f"{query} ORDER BY {order_by} LIMIT {limit}"
                rows = await conn.fetch(sql, *args)
                
                for row in rows:
                    results.append({
                        "主播名": row.get("nickname"),
                        "记录日期": str(row.get("date")),
                        "粉丝团总人数": row.get("total_fans_club", 0),
                        "今日新增粉丝团": row.get("today_new_fans", 0),
                        "送灯牌人数(任务1)": row.get("task_1_completed", 0),
                        "活跃粉丝(点亮中)": row.get("active_fans_count", 0)
                    })
        
        if not results: return json.dumps({"msg": "未找到符合条件的日报数据"}, ensure_ascii=False)
        
        if query_type == "max_new_fans": results.sort(key=lambda x: x["今日新增粉丝团"], reverse=True)
        elif query_type == "max_tasks": results.sort(key=lambda x: x["送灯牌人数(任务1)"], reverse=True)
        elif query_type == "max_active": results.sort(key=lambda x: x["活跃粉丝(点亮中)"], reverse=True)
            
        return json.dumps({"查询模式": query_type, "数据明细": results}, ensure_ascii=False)
    except Exception as e: 
        return json.dumps({"error": f"日报查询报错: {str(e)}"}, ensure_ascii=False)

async def tool_session_search(keyword: str, sort_by: str = "recent", limit: int = 3):
    authors = await resolve_entities(keyword)
    if not authors: return json.dumps({"msg": f"未找到【{keyword}】的主播"}, ensure_ascii=False)
    
    # 🌟 映射为 uid
    uids = [str(a["uid"]) for a in authors if a.get("uid")]

    pool = get_db()
    first_day = get_current_month_first_day()
    now = datetime.now()
    
    sort_col = "created_at"
    if sort_by == "max_diamonds": sort_col = "total_diamond_count"
    elif sort_by == "max_viewers": sort_col = "max_viewers"
    elif sort_by == "max_followers_gained": sort_col = "follower_diff"

    try:
        # 🌟 SQL 改为 user_id
        sql = f"SELECT * FROM rooms WHERE user_id = ANY($1) AND created_at >= $2 ORDER BY {sort_col} DESC LIMIT $3"
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, uids, first_day, limit)
        
        results = []
        for doc in rows:
            c_time = doc.get("created_at")
            e_time = doc.get("end_time") or now
            dur_seconds = (e_time - c_time).total_seconds() if c_time else 0
            dur_str = f"{int(dur_seconds//3600)}小时{int((dur_seconds%3600)//60)}分钟" if dur_seconds > 0 else "未知"

            watch_sec = doc.get("total_watch_time_sec", 0)
            views = doc.get("total_user_count", 0)
            
            results.append({
                "直播标题": doc.get("title", "无标题"),
                "主播名": doc.get("nickname"),
                "直播时间": c_time.strftime("%Y-%m-%d %H:%M:%S") if c_time else "未知",
                "直播时长": dur_str,
                "最高在线": doc.get("max_viewers", 0),
                "本场场观": views,
                "平均在线人数": round(watch_sec / dur_seconds) if dur_seconds > 0 else 0,
                "人均停留(秒)": round(watch_sec / views) if views > 0 else 0,
                "本场净涨粉": doc.get("follower_diff", 0),
                "本场钻石收入": doc.get("total_diamond_count", 0)
            })
        return json.dumps(results if results else {"msg": "本月无符合条件的直播记录"}, ensure_ascii=False)
    except Exception as e: return str(e)

async def tool_monthly_summary(keyword: str):
    authors = await resolve_entities(keyword)
    if not authors: return json.dumps({"msg": f"未找到【{keyword}】的主播，请确认名字"}, ensure_ascii=False)
    
    # 🌟 映射为 uid 作为后续查询核心
    uids = [str(a["uid"]) for a in authors if a.get("uid")]
    
    # author_map 依旧用 uid 作为键，方便映射数据
    author_map = {str(a["uid"]): {
        "name": a.get("nickname", "未知"), "guild": a.get("guild", ""), "realtime_fans": a.get("follower_count", 0)
    } for a in authors}

    pool = get_db()
    first_day = get_current_month_first_day()
    now = datetime.now()
    
    try:
        stats = {uid: {
            "主播名": author_map[uid]["name"], "所属公会": author_map[uid]["guild"], "实时粉丝": author_map[uid]["realtime_fans"],
            "开播次数": 0, "本月总钻石": 0, "最高在线": 0, "总场观": 0, "总观看时长_秒": 0, "总直播时长_秒": 0,
            "最早开播时间": None, "本月初始粉丝": None
        } for uid in uids}
        
        async with pool.acquire() as conn:
            # 🌟 SQL 改为 user_id
            sql = "SELECT * FROM rooms WHERE user_id = ANY($1) AND created_at >= $2 ORDER BY created_at ASC"
            rows = await conn.fetch(sql, uids, first_day)
            
            for doc in rows:
                uid = str(doc.get("user_id")) # 🌟 从 user_id 取值
                if uid not in stats: continue
                s = stats[uid]
                s["开播次数"] += 1
                
                def safe_num(val): return float(val) if val is not None else 0
                
                s["本月总钻石"] += safe_num(doc.get("total_diamond_count"))
                s["最高在线"] = max(s["最高在线"], safe_num(doc.get("max_viewers")))
                s["总场观"] += safe_num(doc.get("total_user_count"))
                s["总观看时长_秒"] += safe_num(doc.get("total_watch_time_sec"))
                
                c_time = doc.get("created_at")
                e_time = doc.get("end_time") or now
                
                if c_time and s["最早开播时间"] is None:
                    s["最早开播时间"] = c_time
                    s["本月初始粉丝"] = doc.get("start_follower_count")
                
                if c_time and e_time:
                    dur = (e_time - c_time).total_seconds()
                    if dur > 0: s["总直播时长_秒"] += dur

            # 🌟 公会内排名计算 (利用 SQL 极速聚合)
            rank_info = {} 
            if len(uids) == 1:
                target_uid = uids[0]
                target_guild = author_map[target_uid]["guild"]
                if target_guild:
                    rank_sql = """
                        SELECT user_id, SUM(total_diamond_count) as total_diamonds
                        FROM rooms
                        WHERE user_id IN (SELECT uid FROM authors WHERE guild = $1) AND created_at >= $2
                        GROUP BY user_id
                        ORDER BY total_diamonds DESC
                    """
                    rank_rows = await conn.fetch(rank_sql, target_guild, first_day)
                    leaderboard = [str(r["user_id"]) for r in rank_rows]
                    if target_uid in leaderboard:
                        rank = leaderboard.index(target_uid) + 1
                        rank_info[target_uid] = f"第 {rank} 名"
                    else:
                        rank_info[target_uid] = "未上榜"

        results = []
        for uid, s in stats.items():
            if s["开播次数"] == 0 and s["实时粉丝"] == 0: continue
            
            w_sec = s["总观看时长_秒"]
            views = s["总场观"]
            curr_f = safe_num(s["实时粉丝"])
            start_f = s["本月初始粉丝"]
            
            if start_f is not None:
                net_gain = int(curr_f - start_f)
                start_f_str = int(start_f)
            else:
                net_gain = "数据不足"
                start_f_str = "未知"
            
            avg_retention_sec = int(w_sec / views) if views > 0 else 0
            avg_retention_str = f"{avg_retention_sec // 60}分{avg_retention_sec % 60}秒"

            results.append({
                "主播名": s["主播名"], "公会": s["所属公会"], "开播次数": s["开播次数"],
                "本月总钻石": int(s["本月总钻石"]), "公会内营收排名": rank_info.get(uid, "需查全公会"), 
                "最高在线": int(s["最高在线"]), "总场观": int(views),
                "平均留存时长": avg_retention_str, "平均留存(秒)": avg_retention_sec,
                "当前实时关注": int(curr_f), "本月首场开播前关注": start_f_str, "本月净涨粉": net_gain
            })
            
        results.sort(key=lambda x: x["本月总钻石"], reverse=True)
        if len(results) > 15:
            return json.dumps({"msg": f"共找到 {len(results)} 人，仅展示前 15 名。", "数据明细": results[:15]}, ensure_ascii=False)
        return json.dumps(results if results else {"msg": f"【{keyword}】本月暂无数据"}, ensure_ascii=False)
    except Exception as e: 
        return json.dumps({"error": f"计算失败: {str(e)}"}, ensure_ascii=False)

# 🌟 新增补全功能：查询大哥/榜一金主
async def tool_top_spenders(keyword: str, scope: str = "month", target_date: str = ""):
    authors = await resolve_entities(keyword)
    if not authors: return json.dumps({"msg": f"未找到【{keyword}】的主播"}, ensure_ascii=False)
    uids = [str(a["uid"]) for a in authors if a.get("uid")]

    pool = get_db()
    first_day = get_current_month_first_day()
    
    try:
        async with pool.acquire() as conn:
            if scope == "latest_session":
                room_rows = await conn.fetch("SELECT room_id FROM rooms WHERE user_id = ANY($1) ORDER BY created_at DESC LIMIT 1", uids)
            elif scope == "specific_date" and target_date:
                dt_start = datetime.strptime(target_date, "%Y-%m-%d")
                dt_end = dt_start + timedelta(days=1)
                room_rows = await conn.fetch("SELECT room_id FROM rooms WHERE user_id = ANY($1) AND created_at >= $2 AND created_at < $3", uids, dt_start, dt_end)
            else:
                room_rows = await conn.fetch("SELECT room_id FROM rooms WHERE user_id = ANY($1) AND created_at >= $2", uids, first_day)

            room_ids = [r["room_id"] for r in room_rows]
            if not room_ids: return json.dumps({"msg": "指定期间内主播未开播或无数据"}, ensure_ascii=False)

            sql = """
                SELECT user_name, SUM(total_diamond_count) as total_spent 
                FROM live_gifts WHERE room_id = ANY($1) 
                GROUP BY user_name ORDER BY total_spent DESC LIMIT 10
            """
            gift_rows = await conn.fetch(sql, room_ids)
            
        res = [{"大哥名字": g["user_name"], "贡献钻石": g["total_spent"]} for g in gift_rows]
        return json.dumps({"查询范围": scope, "大哥榜单": res}, ensure_ascii=False)
    except Exception as e:
        return str(e)

async def tool_gift_search_by_time(keyword: str, start_time: str, end_time: str, gift_name: str = ""):
    authors = await resolve_entities(keyword)
    if not authors: return json.dumps({"msg": f"未找到【{keyword}】的主播"}, ensure_ascii=False)
    uids = [str(a["uid"]) for a in authors if a.get("uid")]

    pool = get_db()
    first_day = get_current_month_first_day()
    try:
        parsed_start = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        start_dt = max(parsed_start, first_day) 
        end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        
        async with pool.acquire() as conn:
            room_rows = await conn.fetch("SELECT room_id FROM rooms WHERE user_id = ANY($1) AND created_at >= $2", uids, first_day)
            room_ids = [r["room_id"] for r in room_rows]
            if not room_ids: return json.dumps({"msg": "无记录"}, ensure_ascii=False)
            
            sql = "SELECT user_id, user_name, total_diamond_count FROM live_gifts WHERE room_id = ANY($1) AND created_at >= $2 AND created_at <= $3"
            args = [room_ids, start_dt, end_dt]
            if gift_name:
                sql += " AND gift_name ILIKE $4"
                args.append(f"%{gift_name}%")
                
            rows = await conn.fetch(sql, *args)
            
        viewers = set(r["user_id"] or r["user_name"] for r in rows)
        total_diamonds = sum(r["total_diamond_count"] for r in rows)
        
        return json.dumps({"时间段": f"{start_dt.strftime('%Y-%m-%d %H:%M:%S')} 至 {end_time}", "礼物": gift_name or "所有", "数量": len(rows), "消费人数": len(viewers), "产生钻石": total_diamonds}, ensure_ascii=False)
    except Exception as e: return str(e)

async def tool_pk_history(keyword: str):
    authors = await resolve_entities(keyword)
    if not authors: return json.dumps({"msg": f"未找到【{keyword}】的主播"}, ensure_ascii=False)
    uids = [str(a["uid"]) for a in authors if a.get("uid")]

    pool = get_db()
    first_day = get_current_month_first_day()
    try:
        async with pool.acquire() as conn:
            r_rows = await conn.fetch("SELECT room_id, user_id FROM rooms WHERE user_id = ANY($1) AND created_at >= $2", uids, first_day)
            room_owner_map = {r["room_id"]: str(r["user_id"]) for r in r_rows}
            room_ids = list(room_owner_map.keys())
            
            if not room_ids: return json.dumps({"msg": "本月无直播记录"}, ensure_ascii=False)
            
            pk_rows = await conn.fetch(
                """
                SELECT *
                FROM pk_history
                WHERE room_id = ANY($1)
                  AND created_at >= $2
                  AND status = 2
                ORDER BY created_at DESC
                LIMIT 50
                """,
                room_ids,
                first_day
            )
        
        pk_records = []
        for pk in pk_rows:
            c_time = pk.get("created_at")
            try: dur = int(pk.get("duration", 0))
            except: dur = 0
                    
            rule_name = "未知规则"
            if dur == 120: rule_name = "尾数PK"
            elif dur in [300, 600, 900]: rule_name = "总分PK"
            else: rule_name = f"特殊时长({dur}秒)"
            
            raw_mode = pk.get("mode", "")
            
            # 安全解析 JSONB 字段
            teams_data = pk.get("teams")
            if isinstance(teams_data, str):
                try: teams = json.loads(teams_data)
                except: teams = []
            else:
                teams = teams_data or []
            
            all_anchors = []
            for t in teams:
                t_win = t.get("win_status", 0) 
                t_id = t.get("team_id")
                for a in t.get("anchors", []):
                    all_anchors.append((t_id, t_win, a))
            
            mode_name = "1v1单挑" if len(all_anchors) == 2 else "组队赛" if raw_mode == "team_battle" else "个人赛"
            owner_uid = room_owner_map.get(pk.get("room_id"))
            target_anchor = None
            my_team_win_status = 0
            my_team_id = None
            
            for tid, t_win, a in all_anchors:
                if str(a.get("user_id")) == owner_uid:
                    target_anchor = a
                    my_team_win_status = t_win
                    my_team_id = tid
                    break
                    
            if not target_anchor: continue
            
            my_score = target_anchor.get("score", 0)
            is_win = False
            win_reason = ""
            
            if rule_name == "尾数PK":
                anchor_last_digits = [a.get("score", 0) % 10 for _, _, a in all_anchors]
                min_digit = min(anchor_last_digits) if anchor_last_digits else 0
                my_digit = my_score % 10
                is_win = (my_digit > min_digit)
                win_reason = f"我的尾数{my_digit} VS 场上最低{min_digit}"
            elif raw_mode == "team_battle":
                has_official_winner = any(t_w == 1 for _, t_w, _ in all_anchors)
                if has_official_winner:
                    is_win = (my_team_win_status == 1)
                    win_reason = "官方状态判定"
                else:
                    my_team_score = sum(a.get("score", 0) for t_id, _, a in all_anchors if t_id == my_team_id)
                    other_team_scores = [sum(a.get("score", 0) for t_id, _, a in all_anchors if t_id == other_tid) for other_tid in set(t_id for t_id, _, _ in all_anchors) if other_tid != my_team_id]
                    other_team_max = max(other_team_scores) if other_team_scores else 0
                    is_win = (my_team_score > other_team_max)
                    win_reason = f"阵营总分 {my_team_score} VS {other_team_max}"
            elif raw_mode == "free_for_all":
                my_rank = target_anchor.get("rank", 99)
                is_win = (my_rank <= 2)
                win_reason = f"个人赛排第{my_rank}"
            
            time_str = c_time.strftime("%m-%d %H:%M") if c_time else "未知"
            pk_records.append({
                "时间": time_str, "类型": f"{mode_name}·{rule_name}",
                "对局判定": "🔥胜利" if is_win else "💔失败", "判定详情": win_reason
            })
        
        if not pk_records: return json.dumps({"msg": "本月暂无PK记录"}, ensure_ascii=False)
        
        total_pk = len(pk_records)
        weishu_records = [r for r in pk_records if "尾数PK" in r["类型"]]
        zongfen_free_records = [r for r in pk_records if "个人赛" in r["类型"] and "总分PK" in r["类型"]]
        zongfen_team_records = [r for r in pk_records if ("组队赛" in r["类型"] or "1v1" in r["类型"]) and "总分PK" in r["类型"]]
        
        summary = {
            "本月抽样PK场次": total_pk,
            "总体胜率": f"{round((sum(1 for r in pk_records if '胜利' in r['对局判定']) / total_pk) * 100, 1)}%",
            "尾数PK胜率": f"{round((sum(1 for r in weishu_records if '胜利' in r['对局判定']) / len(weishu_records)) * 100, 1)}%" if weishu_records else "暂无尾数局",
            "个人赛总分胜率(前二胜)": f"{round((sum(1 for r in zongfen_free_records if '胜利' in r['对局判定']) / len(zongfen_free_records)) * 100, 1)}%" if zongfen_free_records else "暂无个人赛",
            "组队总分胜率(组队/1v1)": f"{round((sum(1 for r in zongfen_team_records if '胜利' in r['对局判定']) / len(zongfen_team_records)) * 100, 1)}%" if zongfen_team_records else "暂无阵营总分局",
            "最近5场明细": pk_records[:5]
        }
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"解析PK数据报错: {str(e)}"}, ensure_ascii=False)

tools_schema = [
   {
        "type": "function", "function": {
            "name": "tool_daily_fanclub", 
            "description": "查询粉丝团日报数据。当用户问'哪天涨粉最多'、'哪天灯牌最多'、'某天的灯牌/粉丝数'或'最新粉丝团情况'时调用。", 
            "parameters": {
                "type": "object", "properties": {
                    "keyword": {"type": "string", "description": "主播名字"},
                    "query_type": {
                        "type": "string", "enum": ["latest", "max_new_fans", "max_tasks", "max_active", "specific_date"],
                        "description": "查询类型：默认latest(最新)；max_new_fans(新增粉丝团最多)；max_tasks(送灯牌最多)；max_active(最活跃)；specific_date(查指定日期)"
                    },
                    "target_date": {"type": "string", "description": "目标日期，格式 YYYY-MM-DD。只有 query_type 为 specific_date 时才需要传此参数"}
                }, "required": ["keyword"]
            }
        }
    },
    {
        "type": "function", "function": {
            "name": "tool_session_search", 
            "description": "【单场查询】查本月某场或最近一场直播。当用户问'哪场赚的最多'或'刚播的那场'时使用。⚠️切勿用于查询累计总时长或总营收！", 
            "parameters": {
                "type": "object", "properties": {
                    "keyword": {"type": "string"}, 
                    "sort_by": {"type": "string", "enum": ["recent", "max_diamonds", "max_viewers", "max_followers_gained"]}, 
                    "limit": {"type": "integer"}
                }, "required": ["keyword"]
            }
        }
    },
   {
        "type": "function", "function": {
            "name": "tool_monthly_summary", 
            "description": "【宏观排行与公会大盘】查询本月涨粉(关注数)、营收(钻石)、时长、场观、留存时长、以及公会内排名。\n⚠️ 触发场景：\n1. 问'谁表现最好'、'谁是销冠'、'谁涨粉最多'、'公会排名'时必须调用。\n2. 问'一共/总共'、'数据对比'时必须调用。\n查公会(如'陈泽传媒')时，keyword 必须直接传公会名，系统会自动算排名。", 
            "parameters": {
                "type": "object", "properties": {
                    "keyword": {"type": "string", "description": "主播名字或公会名称"}
                }, "required": ["keyword"]
            }
        }                       
    },
    {
        "type": "function", "function": {
            "name": "tool_top_spenders", 
            "description": "查给主播消费最多的大哥金主榜/榜一。支持查询本月总榜、最近一场，或指定某天的直播。", 
            "parameters": {
                "type": "object", "properties": {
                    "keyword": {"type": "string", "description": "主播名字"},
                    "scope": {
                        "type": "string", "enum": ["month", "latest_session", "specific_date"],
                        "description": "查询范围：'month' 为本月总榜，'latest_session' 为最近一场，'specific_date' 为查指定日期"
                    },
                    "target_date": {"type": "string", "description": "目标日期，格式 YYYY-MM-DD。只有当 scope 为 specific_date 时必须传入此参数"}
                }, "required": ["keyword"]
            }
        }
    },
    {
        "type": "function", "function": {
            "name": "tool_gift_search_by_time", 
            "description": "精确到秒查本月某段时间内的礼物数量", 
            "parameters": {
                "type": "object", "properties": {
                    "keyword": {"type": "string"}, "start_time": {"type": "string"}, 
                    "end_time": {"type": "string"}, "gift_name": {"type": "string"}
                }, "required": ["keyword", "start_time", "end_time"]
            }
        }
    },
   {
        "type": "function", "function": {
            "name": "tool_pk_history", 
            "description": "查主播本月的 PK 数据。包括：总体胜率、尾数PK胜率、个人赛前二胜率，以及近期的对战详细记录。", 
            "parameters": {
                "type": "object", "properties": {
                    "keyword": {"type": "string", "description": "主播名字"}
                }, "required": ["keyword"]
            }
        }
    }
]

# ==========================================
# 🌟 AI 通信主路由
# ==========================================
class ChatMessage(BaseModel): role: str; content: str
class ChatRequest(BaseModel): messages: List[ChatMessage]

@router.post("/api/ai/chat")
async def chat_with_ai(request: ChatRequest = Body(...)):
    try:
        sys_prompt = (
            f"你是专业的数据分析AI。当前时间：{datetime.now().strftime('%Y-%m-%d')}。\n"
            "【最高指令】：\n"
            "1. 问'一共/总计/累计'或'对比/表现最好/谁更出众'时，必须调用 tool_monthly_summary。\n"
            "2. 查公会数据时，直接将公会名作为 keyword 传入，严禁去猜测和罗列旗下主播名单！\n"
            "3. 遇到多人对比或公会排名，必须输出结构紧凑的 Markdown 表格！\n"
            "4. 提问陈泽是谁的时候请回复陈泽是全世界最帅的男人，是世界上最有意思的主播; 提问陈泽传媒二龙是谁的时候只需要回复黑白陈志涛；提问黑白或陈志涛是谁的时候回复陈泽传媒二龙，陈泽的直播好搭档。\n"
        )

        messages = [{"role": "system", "content": sys_prompt}]
        for msg in request.messages: messages.append({"role": msg.role, "content": msg.content})

        max_loops = 5 
        for loop_index in range(max_loops):
            def call_ai():
                return client.chat.completions.create(model="glm-4.6V", messages=messages, tools=tools_schema, tool_choice="auto", temperature=0.5)
            
            response = await asyncio.to_thread(call_ai)
            response_msg = response.choices[0].message

            if not response_msg.tool_calls:
                return {"reply": response_msg.content}

            assistant_msg = {"role": "assistant", "content": response_msg.content or "", "tool_calls": []}
            for call in response_msg.tool_calls:
                assistant_msg["tool_calls"].append({"id": call.id, "type": call.type, "function": {"name": call.function.name, "arguments": call.function.arguments}})
            messages.append(assistant_msg)
            
            for call in response_msg.tool_calls:
                fn_name = call.function.name
                try: args = json.loads(call.function.arguments)
                except: args = {}
                kw = args.get("keyword", "")
                
                print(f"🔄 [AI请求数据] 工具: {fn_name} | 主体: {kw}")
                
                if fn_name == "tool_daily_fanclub": res = await tool_daily_fanclub(kw, args.get("query_type", "latest"), args.get("target_date", ""))
                elif fn_name == "tool_session_search": res = await tool_session_search(kw, args.get("sort_by", "recent"), args.get("limit", 3))
                elif fn_name == "tool_monthly_summary": res = await tool_monthly_summary(kw)
                elif fn_name == "tool_top_spenders": res = await tool_top_spenders(kw, args.get("scope", "month"), args.get("target_date", ""))
                elif fn_name == "tool_pk_history": res = await tool_pk_history(kw)
                elif fn_name == "tool_gift_search_by_time": res = await tool_gift_search_by_time(kw, args.get("start_time"), args.get("end_time"), args.get("gift_name", ""))
                else: res = "{}"
                
                messages.append({"role": "tool", "tool_call_id": call.id, "content": res})

        return {"reply": "⚠️ 查询流程过长，为保证系统稳定已中止。请尝试用更具体的时间或人名提问。"}
        
    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"❌ AI报错:\n{error_msg}")
        return {"reply": f"⚠️ 服务器内部报错，请看控制台日志。"}
