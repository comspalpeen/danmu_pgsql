# daily_reporter.py
import logging
import asyncio
import aiohttp
import random
import orjson as json
from datetime import datetime
from src.utils.fetcher_utils import extract_filename  # ✅ 引入瘦身工具

logger = logging.getLogger("DailyReporter")

class DailyReporter:
    def __init__(self, db_handler):
        self.db = db_handler
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    async def get_random_cookie(self):
        """从 PG 数据库获取一个随机的真实 Cookie"""
        if self.db:
            cookies = await self.db.get_all_cookies()
            if cookies:
                return random.choice(cookies)
        return None

    async def fetch_fans_club_info(self, session, uid, sec_uid, cookie):
        """接口1: 获取粉丝团数据 (需要 Cookie)"""
        url = "https://live.douyin.com/webcast/fansclub/club_user_list/"
        params = {
            "aid": "6383", "app_name": "douyin_web", "live_id": "1", "device_platform": "web",
            "language": "zh-CN", "cookie_enabled": "true", "screen_width": "1920", "screen_height": "1080",
            "browser_language": "zh-CN", "browser_platform": "Win32", "browser_name": "Edge", "browser_version": "120.0.0.0",
            "anchor_id": uid, "anchor_id_str": uid, "sec_anchor_id": sec_uid,
            "offset": "0", "count": "20"
        }
        headers = {
            "User-Agent": self.user_agent, "Cookie": cookie, "Referer": "https://live.douyin.com/"
        }

        try:
            async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                text = await resp.text()
                data = json.loads(text)
                club_info = data.get("data", {}).get("club_info", {})
                
                # 剔除 club_name，仅保留我们需要的数据
                result = {
                    "active_fans_count": club_info.get("active_fans_count", 0),
                    "total_fans_club": club_info.get("total_fans_count", 0),
                    "today_new_fans": club_info.get("today_new_fans_count", 0),
                    "task_1_completed": 0
                }

                task_stats = club_info.get("task_stats", [])
                for task in task_stats:
                    if task.get("task_type") == 1:
                        result["task_1_completed"] = task.get("compeleted_user_count", 0)
                        break
                return result
        except Exception as e:
            logger.error(f"❌ [API 1] 粉丝团接口失败 (UID: {uid}): {e}")
            return None

    async def fetch_user_profile(self, session, sec_uid):
        """接口2: 获取个人主页信息 (无需 Cookie)"""
        url = "https://live.douyin.com/webcast/user/"
        params = {
            "aid": "6383", "live_id": "1", "device_platform": "web",
            "language": "zh-CN", "sec_target_uid": sec_uid
        }
        headers = {"User-Agent": self.user_agent}

        try:
            async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                text = await resp.text()
                data = json.loads(text)
                user_data = data.get("data", {})
                
                follower_count = user_data.get("follow_info", {}).get("follower_count", 0)
                
                avatar_url = ""
                avatar_thumb = user_data.get("avatar_thumb", {})
                if avatar_thumb and avatar_thumb.get("url_list"):
                    avatar_url = avatar_thumb["url_list"][0]

                pay_grade_icon = ""
                pay_grade_level = 0
                for badge in user_data.get("badge_image_list", []):
                    content = badge.get("content", {})
                    if "荣誉等级" in content.get("alternative_text", ""):
                        if badge.get("url_list"): pay_grade_icon = badge["url_list"][0]
                        pay_grade_level = content.get("level", 0)
                        break

                return {
                    "nickname": user_data.get("nickname", ""),
                    "follower_count": follower_count,
                    "avatar_url": avatar_url,
                    "pay_grade_icon": pay_grade_icon,
                    "pay_grade_level": pay_grade_level
                }
        except Exception as e:
            logger.error(f"❌ [API 2] 个人主页接口失败 (SecUID: {sec_uid[:10]}...): {e}")
            return None

    async def generate_report(self):
        logger.info("📅 [日报] 开始执行每日数据抓取...")
        
        cookie = await self.get_random_cookie()
        if not cookie:
            logger.error("❌ [日报] 终止: 数据库中没有可用的 Cookie")
            return

        # ✅ 改用 PostgreSQL 语法查询目标用户
        users = []
        if self.db and self.db.pool:
            sql = """
                SELECT uid, sec_uid, nickname, avatar 
                FROM authors 
                WHERE follower_count > 1000 
                  AND sec_uid IS NOT NULL AND sec_uid != '';
            """
            try:
                async with self.db.pool.acquire() as conn:
                    records = await conn.fetch(sql)
                    users = [dict(r) for r in records]
            except Exception as e:
                logger.error(f"❌ [日报] 查询 authors 表失败: {e}")
                return
        
        if not users:
            logger.warning("⚠️ [日报] 没有找到符合条件(粉丝>1000)的用户，跳过")
            return

        logger.info(f"📊 [日报] 目标用户数: {len(users)} (筛选条件: >1000粉丝) | 使用 Cookie: {cookie[:20]}...")
        
        reports_batch = []
        # PostgreSQL 的 DATE 类型可以直接用这种格式接收
        today_date_str = datetime.now().strftime("%Y-%m-%d")

        async with aiohttp.ClientSession() as session:
            for user in users:
                uid = user.get('uid')
                sec_uid = user.get('sec_uid')
                db_nickname = user.get('nickname', '未知')
                db_avatar = user.get('avatar', '')

                task_club = self.fetch_fans_club_info(session, uid, sec_uid, cookie)
                task_profile = self.fetch_user_profile(session, sec_uid)
                
                try:
                    res_club, res_profile = await asyncio.gather(task_club, task_profile)
                    
                    if not res_club and not res_profile:
                        logger.warning(f"⚠️ [日报] 用户 {db_nickname} 数据全空，跳过")
                        continue

                    # 头像兜底并瘦身
                    raw_avatar = res_profile["avatar_url"] if res_profile and res_profile.get("avatar_url") else db_avatar
                    clean_avatar = extract_filename(raw_avatar)
                    
                    # 财富等级图标瘦身
                    clean_pay_icon = extract_filename(res_profile.get("pay_grade_icon", "") if res_profile else "")

                    # 组装为 Tuple 以便 PG executemany 批量写入 (彻底移除了 sec_uid 和 club_name)
                    reports_batch.append((
                        datetime.strptime(today_date_str, "%Y-%m-%d").date(), # date
                        uid,                                                  # uid
                        res_profile.get("nickname") or db_nickname,           # nickname
                        clean_avatar,                                         # avatar_url
                        clean_pay_icon,                                       # pay_grade_icon
                        res_profile.get("pay_grade_level", 0) if res_profile else 0,
                        res_profile.get("follower_count", 0) if res_profile else 0,
                        res_club.get("active_fans_count", 0) if res_club else 0,
                        res_club.get("total_fans_club", 0) if res_club else 0,
                        res_club.get("today_new_fans", 0) if res_club else 0,
                        res_club.get("task_1_completed", 0) if res_club else 0
                    ))
                    
                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"❌ [日报] 处理用户 {db_nickname} 异常: {e}")

        # ✅ 用 PG 的 Upsert (ON CONFLICT) 批量入库
        if reports_batch and self.db and self.db.pool:
            try:
                upsert_sql = """
                    INSERT INTO daily_reports (
                        date, uid, nickname, avatar_url, pay_grade_icon, pay_grade_level,
                        follower_count, active_fans_count, total_fans_club, today_new_fans, task_1_completed
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (date, uid) DO UPDATE SET
                        nickname = EXCLUDED.nickname,
                        avatar_url = EXCLUDED.avatar_url,
                        pay_grade_icon = EXCLUDED.pay_grade_icon,
                        pay_grade_level = EXCLUDED.pay_grade_level,
                        follower_count = EXCLUDED.follower_count,
                        active_fans_count = EXCLUDED.active_fans_count,
                        total_fans_club = EXCLUDED.total_fans_club,
                        today_new_fans = EXCLUDED.today_new_fans,
                        task_1_completed = EXCLUDED.task_1_completed;
                """
                async with self.db.pool.acquire() as conn:
                    await conn.executemany(upsert_sql, reports_batch)
                logger.info(f"✅ [日报] 成功生成并更新 {len(reports_batch)} 条记录")
            except Exception as e:
                logger.error(f"❌ [日报] 写入 PostgreSQL 失败: {e}")