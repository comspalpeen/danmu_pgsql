# routers/tieba.py
from fastapi import APIRouter, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
# 👇 1. 改这里：引入 get_tieba_db
from backend_api.common.database import get_tieba_db

router = APIRouter(prefix="/api/tieba", tags=["贴吧监控"]) # 加上 /api 前缀

class TiebaFeedItem(BaseModel):
    source_type: str        
    tid: str                
    fname: str              
    thread_title: str       
    hit_content: str        
    raw_contents: Optional[str] = None  # 🚀 新增：原始 JSON 结构数据
    nick_name: str           
    portrait: str           
    create_time: datetime 

@router.get("/feed", response_model=List[TiebaFeedItem])
async def get_tieba_feed(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    limit: int = Query(5, description="单次加载条数"), # 配合你的极端测试，默认改成5
    offset: int = Query(0, description="数据偏移量"),
    view_mode: str = Query("grouped", description="模式: grouped(折叠) / flat(平铺)")
):
    pool = get_tieba_db()
    search_term = f"%{keyword}%" if keyword else None

    # 第一部分：获取所有的命中条目
    base_sql = """
        WITH hit_candidates AS (
            SELECT 'thread' AS source_type, t.tid, COALESCE(t."text", t.title) AS hit_content, 
                   t.contents AS raw_contents, -- 🚀 提取 contents
                   t.author_id, t.create_time AS hit_time
            FROM tieba_folder.thread t
            WHERE t.reply_num < 800
              AND (t.title ILIKE '%cz%' OR t.title LIKE '%四眼%' OR t.title LIKE '%陈泽%' OR t.title LIKE '%泽神%' OR t."text" ILIKE '%cz%' OR t."text" LIKE '%四眼%' OR t."text" LIKE '%陈泽%' OR t."text" LIKE '%泽神%')
              AND ($1::text IS NULL OR t.title LIKE $1 OR t."text" LIKE $1)
            UNION ALL
            SELECT 'post' AS source_type, p.tid, p."text" AS hit_content, 
                   p.contents AS raw_contents, -- 🚀 提取 contents
                   p.author_id, p.create_time AS hit_time
            FROM tieba_folder.post p JOIN tieba_folder.thread t ON p.tid = t.tid
            WHERE t.reply_num < 800
              AND (p."text" ILIKE '%cz%' OR p."text" LIKE '%四眼%' OR p."text" LIKE '%陈泽%' OR p."text" LIKE '%泽神%')
              AND ($1::text IS NULL OR p."text" LIKE $1)
            UNION ALL
            SELECT 'comment' AS source_type, c.tid, c."text" AS hit_content, 
                   c.contents AS raw_contents, -- 🚀 提取 contents
                   c.author_id, c.create_time AS hit_time
            FROM tieba_folder."comment" c JOIN tieba_folder.thread t ON c.tid = t.tid
            WHERE t.reply_num < 800
              AND (c."text" ILIKE '%cz%' OR c."text" LIKE '%四眼%' OR c."text" LIKE '%陈泽%' OR c."text" LIKE '%泽神%')
              AND ($1::text IS NULL OR c."text" LIKE $1)
        ),
    """
    
    # 🚀 第二部分：根据前端传来的模式，动态决定是否折叠去重
    if view_mode == "flat":
        extract_sql = """
        latest_hits AS (
            -- 💡 修复：这里加上 raw_contents
            SELECT source_type, tid, hit_content, raw_contents, author_id, hit_time 
            FROM hit_candidates ORDER BY hit_time DESC
        )
        """
    else:
        extract_sql = """
        latest_hits AS (
            -- 💡 修复：这里加上 raw_contents
            SELECT DISTINCT ON (tid) source_type, tid, hit_content, raw_contents, author_id, hit_time 
            FROM hit_candidates ORDER BY tid, hit_time DESC
        )
        """

    # 第三部分：关联用户信息并分页
    tail_sql = """
        SELECT lh.source_type, lh.tid::text, COALESCE(f.fname, '未知贴吧') AS fname, t.title AS thread_title,
               lh.hit_content, lh.raw_contents, -- 🚀 这里
               COALESCE(u.user_name, u.nick_name, lh.author_id::text) AS nick_name,
               COALESCE(u.portrait, '') AS portrait, lh.hit_time AS create_time
        FROM latest_hits lh
        JOIN tieba_folder.thread t ON lh.tid = t.tid
        LEFT JOIN tieba_folder.forum f ON t.fid = f.fid
        LEFT JOIN tieba_folder."user" u ON lh.author_id = u.user_id
        ORDER BY lh.hit_time DESC
        LIMIT $2 OFFSET $3;
    """
    
    async with pool.acquire() as conn:
        records = await conn.fetch(base_sql + extract_sql + tail_sql, search_term, limit, offset)
        
    result = []
    for r in records:
        result.append(TiebaFeedItem(
            source_type=r['source_type'],
            tid=r['tid'],
            fname=r['fname'],
            thread_title=r['thread_title'],
            hit_content=r['hit_content'],
            nick_name=r['nick_name'],
            portrait=r['portrait'],
            create_time=r['create_time']
        ))
        
    return result
    
    
@router.get("/thread/{tid}")
async def get_thread_detail(tid: int):
    """
    获取单个帖子的完整详情（主楼 + 回复 + 楼中楼嵌套）。
    """
    pool = get_tieba_db()
    
    # 1. 获取主楼信息
    thread_sql = """
        SELECT t.tid::text, t.title, t."text" AS content, t.contents AS raw_contents, t.create_time,
               COALESCE(u.user_name, u.nick_name, t.author_id::text) AS nick_name, COALESCE(u.portrait, '') AS portrait
        FROM tieba_folder.thread t
        LEFT JOIN tieba_folder."user" u ON t.author_id = u.user_id
        WHERE t.tid = $1
    """
    
    # 2. 获取所有回复信息
    posts_sql = """
        SELECT p.pid::text, p."text" AS content, p.contents AS raw_contents, p.create_time,
               COALESCE(u.user_name, u.nick_name, p.author_id::text) AS nick_name, COALESCE(u.portrait, '') AS portrait
        FROM tieba_folder.post p
        LEFT JOIN tieba_folder."user" u ON p.author_id = u.user_id
        WHERE p.tid = $1
        ORDER BY p.create_time ASC
    """

    # 3. 🚀新增：获取所有楼中楼(子评论)信息
    comments_sql = """
        SELECT c.cid::text, c.pid::text, c."text" AS content, c.contents AS raw_contents, c.create_time,
               COALESCE(u.user_name, u.nick_name, c.author_id::text) AS nick_name, COALESCE(u.portrait, '') AS portrait
        FROM tieba_folder."comment" c
        LEFT JOIN tieba_folder."user" u ON c.author_id = u.user_id
        WHERE c.tid = $1
        ORDER BY c.create_time ASC
    """
    
    async with pool.acquire() as conn:
        thread_info = await conn.fetchrow(thread_sql, tid)
        posts_info = await conn.fetch(posts_sql, tid)
        comments_info = await conn.fetch(comments_sql, tid)
        
    if not thread_info:
        return {"error": "帖子不存在或已被清洗"}
        
    # 将楼中楼按照 pid 分组
    comments_by_pid = {}
    for c in comments_info:
        pid = c['pid']
        if pid not in comments_by_pid:
            comments_by_pid[pid] = []
        comments_by_pid[pid].append(dict(c))
        
    # 组装最终的 posts 列表，把 comments 塞进去
    posts_list = []
    for p in posts_info:
        p_dict = dict(p)
        p_dict['comments'] = comments_by_pid.get(p['pid'], [])
        posts_list.append(p_dict)

    return {
        "thread": dict(thread_info),
        "posts": posts_list
    }
@router.get("/stats")
async def get_tieba_stats():
    """获取极纯净版的昨日大盘情报统计（仅计算命中目标词的精准发言数）"""
    pool = get_tieba_db()
    
    # 神级 SQL：只统计昨天那一句“真真切切命中了关键词”的话，且排除800楼以上的废楼
    sql = """
        WITH yesterday_threads AS (
            SELECT author_id FROM tieba_folder.thread 
            WHERE create_time >= CURRENT_DATE - INTERVAL '1 day' AND create_time < CURRENT_DATE
              AND reply_num < 800
              AND (title ILIKE '%cz%' OR title LIKE '%四眼%' OR title LIKE '%陈泽%' OR title LIKE '%泽神%' OR "text" ILIKE '%cz%' OR "text" LIKE '%四眼%' OR "text" LIKE '%陈泽%' OR "text" LIKE '%泽神%')
        ),
        yesterday_posts AS (
            SELECT p.author_id FROM tieba_folder.post p JOIN tieba_folder.thread t ON p.tid = t.tid
            WHERE p.create_time >= CURRENT_DATE - INTERVAL '1 day' AND p.create_time < CURRENT_DATE
              AND t.reply_num < 800
              AND (p."text" ILIKE '%cz%' OR p."text" LIKE '%四眼%' OR p."text" LIKE '%陈泽%' OR p."text" LIKE '%泽神%')
        ),
        yesterday_comments AS (
            SELECT c.author_id FROM tieba_folder."comment" c JOIN tieba_folder.thread t ON c.tid = t.tid
            WHERE c.create_time >= CURRENT_DATE - INTERVAL '1 day' AND c.create_time < CURRENT_DATE
              AND t.reply_num < 800
              AND (c."text" ILIKE '%cz%' OR c."text" LIKE '%四眼%' OR c."text" LIKE '%陈泽%' OR c."text" LIKE '%泽神%')
        )
        SELECT 
            (SELECT COUNT(*) FROM yesterday_threads) AS new_threads,
            (SELECT COUNT(*) FROM yesterday_posts) AS new_posts,
            (SELECT COUNT(*) FROM yesterday_comments) AS new_comments,
            (SELECT COUNT(DISTINCT author_id) FROM (
                SELECT author_id FROM yesterday_threads UNION ALL
                SELECT author_id FROM yesterday_posts UNION ALL
                SELECT author_id FROM yesterday_comments
            ) AS all_users) AS active_users;
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql)
        
    return dict(row) if row else {"new_threads": 0, "new_posts": 0, "new_comments": 0, "active_users": 0}