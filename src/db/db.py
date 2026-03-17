# db.py
import time
import asyncio
import orjson
from datetime import datetime
import logging
import asyncpg
from src.db.redis_client import get_redis
from src.utils.fetcher_utils import extract_filename
import hashlib

logger = logging.getLogger("DB")

def to_dt(ts):
    """将 Float 时间戳极速转为 PostgreSQL 支持的 datetime 对象"""
    if not ts: return datetime.now()
    try:
        return datetime.fromtimestamp(ts)
    except Exception:
        return datetime.now()

class AsyncPostgresHandler:
    def __init__(self, dsn=None):
        if not dsn:
            from config import PG_DSN
            dsn = PG_DSN
        self.dsn = dsn
        self.pool = None
        
        self.REDIS_CHAT_KEY = "buffer:chats"
        self.REDIS_GIFT_KEY = "buffer:gifts"
        self.REDIS_CHAT_BACKUP_KEY = "buffer:chats:processing"
        self.REDIS_GIFT_BACKUP_KEY = "buffer:gifts:processing"
        
        self.BUFFER_TIMEOUT = 10 
        self.BATCH_TRIGGER_SIZE = 1500
        
        self.CHAT_LAST_WRITE_TIME = time.time()
        self.GIFT_LAST_WRITE_TIME = time.time()
        
        self._chat_push_count_soft = 0
        self._gift_push_count_soft = 0
        
        self._flush_chat_task = None
        self._flush_gift_task = None
        self._shutting_down = False

        self.FLUSH_MAX_RETRIES  = 5
        self.FLUSH_BASE_BACKOFF = 2   
        self.FLUSH_MAX_BACKOFF  = 60  
        self._gift_retry_count  = 0
        self._chat_retry_count  = 0

        self.SAFE_BATCH_POP_SCRIPT = """
        local source = KEYS[1]
        local dest = KEYS[2]
        local count = tonumber(ARGV[1])
        local items = redis.call('LPOP', source, count)
        if items and #items > 0 then
            redis.call('RPUSH', dest, unpack(items)) -- 🌟 O(1) 级别的底层批量推入
        end
        return items
        """
        self.UPSERT_USERS_SQL = """
            INSERT INTO users (user_id, sec_uid, display_id, user_name, gender, pay_grade, avatar_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (user_id) DO UPDATE SET
                sec_uid = EXCLUDED.sec_uid,
                display_id = CASE WHEN EXCLUDED.display_id != '' THEN EXCLUDED.display_id ELSE users.display_id END,
                user_name = EXCLUDED.user_name, gender = EXCLUDED.gender,
                pay_grade = GREATEST(users.pay_grade, EXCLUDED.pay_grade),
                avatar_url = EXCLUDED.avatar_url, updated_at = CURRENT_TIMESTAMP;
        """
        
        self.UPSERT_CZ_FANS_SQL = """
            INSERT INTO cz_fans (user_id, cz_club_level, last_active_time)
            VALUES ($1, $2, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                cz_club_level = GREATEST(cz_fans.cz_club_level, EXCLUDED.cz_club_level),
                last_active_time = CURRENT_TIMESTAMP;
        """
    async def init_pool(self):
        try:
            self.pool = await asyncpg.create_pool(
                dsn=self.dsn, min_size=5, max_size=20, ssl=False,
                command_timeout=60, timeout=10, max_inactive_connection_lifetime=300
            )
            logger.info("✅ [AsyncPg] PostgreSQL 连接池初始化完成")
            await self._recover_backup_queues()
        except Exception as e:
            logger.error(f"❌ PostgreSQL 初始化失败: {e}")
            raise e

    async def _recover_backup_queues(self):
        try:
            redis_client = get_redis()
            for backup_key, main_key in [
                (self.REDIS_GIFT_BACKUP_KEY, self.REDIS_GIFT_KEY),
                (self.REDIS_CHAT_BACKUP_KEY, self.REDIS_CHAT_KEY)
            ]:
                while True:
                    items = await redis_client.lpop(backup_key, count=1000)
                    if not items: break
                    await redis_client.lpush(main_key, *items[::-1])
                    logger.warning(f"🚑 [恢复] 从 {backup_key} 抢救回 {len(items)} 条数据！")
        except Exception as e:
            logger.error(f"❌ 恢复备份队列失败: {e}")

    def _get_user_fingerprint(self, uid, sec_uid, display_id, user_name, gender, pay_grade, avatar_url):
        raw = f"{uid}_{sec_uid}_{display_id}_{user_name}_{gender}_{pay_grade}_{avatar_url}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    # =========================================================================
    # 🌟 核心：大一统数据冲刷流水线 (The Unified Pipeline)
    # =========================================================================
    async def process_light_stick(self, data: dict):
        data['_is_light_stick'] = True
        await self.insert_gift(data)

    async def insert_gift(self, data: dict): await self._insert_buffer('gift', data)
    async def insert_chat(self, data: dict): await self._insert_buffer('chat', data)
    async def _insert_buffer(self, data_type: str, data: dict):
        """🌟 统一处理 Chat 和 Gift 的缓冲、计数与触发机制"""
        if not data or self._shutting_down: return
        try:
            if not data.get('created_at'): data['created_at'] = time.time()
            
            # 动态获取对应的 Redis Key 和 计数器
            redis_key = getattr(self, f"REDIS_{data_type.upper()}_KEY")
            await get_redis().rpush(redis_key, orjson.dumps(data))
            
            count_attr = f"_{data_type}_push_count_soft"
            time_attr = f"{data_type.upper()}_LAST_WRITE_TIME"
            task_attr = f"_flush_{data_type}_task"
            
            # 动态更新计数
            current_count = getattr(self, count_attr) + 1
            setattr(self, count_attr, current_count)
            last_time = getattr(self, time_attr)
            
            # 判断是否触发写库任务
            if (time.time() - last_time > self.BUFFER_TIMEOUT) or (current_count >= self.BATCH_TRIGGER_SIZE):
                task = getattr(self, task_attr)
                if task is None or task.done():
                    # 动态启动对应的 Flush 任务
                    setattr(self, task_attr, asyncio.create_task(self._flush_buffer_pipeline(data_type)))
        except Exception as e: 
            logger.error(f"❌ [DB] 缓冲{data_type}失败: {e}")
    async def flush_gift_buffer(self):
        await self._flush_buffer_pipeline('gift')

    async def flush_chat_buffer(self):
        await self._flush_buffer_pipeline('chat')

    async def _flush_buffer_pipeline(self, data_type: str):
        """🌟 统一处理 Chat 和 Gift 的数据解析、节流阀拦截、以及回写数据库"""
        redis_client = get_redis()
        
        if data_type == 'gift':
            self.GIFT_LAST_WRITE_TIME = time.time()
            self._gift_push_count_soft = 0
            main_key, backup_key = self.REDIS_GIFT_KEY, self.REDIS_GIFT_BACKUP_KEY
        else:
            self.CHAT_LAST_WRITE_TIME = time.time()
            self._chat_push_count_soft = 0
            main_key, backup_key = self.REDIS_CHAT_KEY, self.REDIS_CHAT_BACKUP_KEY

        while True:
            try:
                raw_data_list = await redis_client.eval(self.SAFE_BATCH_POP_SCRIPT, 2, main_key, backup_key, self.BATCH_TRIGGER_SIZE)
                if not raw_data_list: break
            except Exception as e:
                logger.error(f"❌ [DB] Redis 批量弹队({data_type})异常: {e}")
                break
            
            users_batch, specific_batch, room_updates = {}, [], {}
            raw_cz_fans = {} # 暂存本批次所有陈泽直播间活跃粉丝
            
            # ================= 1. 数据解析层 =================
            for idx, raw in enumerate(raw_data_list):
                if idx % 50 == 0: await asyncio.sleep(0)
                try:
                    data = orjson.loads(raw)
                    uid = data.get('user_id')
                    room_id = data.get('room_id')
                    web_rid = data.get('web_rid', '')
                    if not uid or not room_id: continue

                    clean_avatar = extract_filename(data.get('avatar_url', ''))
                    clean_pay_icon = extract_filename(data.get('pay_grade_icon', ''))
                    clean_fans_icon = extract_filename(data.get('fans_club_icon', ''))
                    
                    # ==========================================
                    # 🛡️ 内存级防线：处理本批次内的无脑覆盖漏洞
                    # ==========================================
                    current_pay = data.get('pay_grade', 0)
                    current_cz_level = data.get('cz_club_level', 0)
                    
                    # 1. 统一构建全站用户字典 (维持最高消费等级、保留有效字段)
                    existing_user = users_batch.get(uid)
                    if existing_user:
                        current_pay = max(current_pay, existing_user[5]) # 索引5是 pay_grade
                        clean_avatar = clean_avatar or existing_user[6]  # 防止新数据头像为空覆盖旧数据

                    users_batch[uid] = (
                        uid, 
                        data.get('sec_uid', '') or (existing_user[1] if existing_user else ''), 
                        data.get('display_id', '') or (existing_user[2] if existing_user else ''),
                        data.get('user_name', '') or (existing_user[3] if existing_user else ''), 
                        data.get('gender', 0), 
                        current_pay, 
                        clean_avatar
                    )

                    # 2. 收集陈泽房间活跃者 (维持本批次内的最高粉丝等级)
                    if str(web_rid) == "615189692839":
                        existing_fan = raw_cz_fans.get(uid)
                        if existing_fan:
                            current_cz_level = max(current_cz_level, existing_fan[1]) # 索引1是 cz_club_level
                        raw_cz_fans[uid] = (uid, current_cz_level)
                    # ==========================================

                    # 差异化解析
                    if data_type == 'gift':
                        is_light_stick = data.get('_is_light_stick', False)
                        clean_gift_icon = extract_filename(data.get('gift_icon_url', ''))
                        diamond_count = data.get('diamond_count', 0)
                        combo_count = data.get('combo_count', 1)
                        group_count = data.get('group_count', 1)
                        total_diamond = data.get('total_diamond_count') or (diamond_count * combo_count * group_count)

                        if not is_light_stick:
                            specific_batch.append((
                                web_rid, room_id, uid, data.get('user_name', ''), data.get('gift_id', ''), data.get('gift_name', ''), 
                                clean_gift_icon, diamond_count, combo_count, group_count, total_diamond,
                                data.get('pay_grade', 0), clean_pay_icon, data.get('fans_club_level', 0), clean_fans_icon, 
                                to_dt(data.get('send_time')), to_dt(data.get('created_at'))
                            ))

                        if room_id not in room_updates: room_updates[room_id] = {'diamond': 0, 'ticket': 0}
                        if is_light_stick:
                            room_updates[room_id]['ticket'] += 1
                            room_updates[room_id]['diamond'] += diamond_count
                        elif total_diamond > 0:
                            room_updates[room_id]['diamond'] += total_diamond
                            
                    elif data_type == 'chat':
                        specific_batch.append((
                            web_rid, room_id, uid, data.get('user_name', ''), data.get('content', ''), 
                            data.get('pay_grade', 0), clean_pay_icon, data.get('fans_club_level', 0), clean_fans_icon, 
                            to_dt(data.get('event_time')), to_dt(data.get('created_at'))
                        ))
                        room_updates[room_id] = room_updates.get(room_id, 0) + 1
                        
                except Exception: pass

            db_success = False
            if not specific_batch and not users_batch: 
                db_success = True 
            else:
                # ================= 2. Redis 高速缓存拦截层 =================
                cz_fans_batch = {}
                cz_active_cache_updates = {}
                
                # 🌟 2.1 智能 2 小时节流阀 (支持等级跃迁检测)
                if raw_cz_fans:
                    redis_keys = [f"cz_active:{uid}" for uid in raw_cz_fans.keys()]
                    try: 
                        # 批量获取缓存中的历史等级
                        active_levels = await redis_client.mget(redis_keys)
                    except Exception: 
                        active_levels = [None] * len(redis_keys)
                    
                    for idx, (uid, fan_tuple) in enumerate(raw_cz_fans.items()):
                        current_level = fan_tuple[1] # 本次抓取到的最新等级
                        cached_val = active_levels[idx]
                        
                        # 解析缓存中的等级（如果没缓存则为 -1）
                        cached_val = active_levels[idx]
                        # 🌟 暴力强转，防弹级容错，无视 str 还是 bytes
                        try:
                            cached_level = int(cached_val) if cached_val is not None else -1
                        except (ValueError, TypeError):
                            cached_level = -1
                        
                        # 💡 核心破盾逻辑：如果没在冷却期，或者他的等级变高了！
                        if cached_level == -1 or current_level > cached_level: 
                            cz_fans_batch[uid] = fan_tuple
                            # 把最新的等级存入 Redis，并重新开始 2 小时计时
                            cz_active_cache_updates[f"cz_active:{uid}"] = str(current_level).encode('utf-8')
                # 2.2 全局画像防抖 Hash 过滤
                users_to_update, hashes_to_cache = [], {}
                if users_batch:
                    redis_keys = [f"user:hash:{uid}" for uid in users_batch.keys()]
                    user_hashes = {uid: self._get_user_fingerprint(*tup) for uid, tup in users_batch.items()}
                    try: old_hashes = await redis_client.mget(redis_keys)
                    except Exception: old_hashes = [None] * len(redis_keys)
                        
                    for idx, (uid, user_tuple) in enumerate(users_batch.items()):
                        new_hash = user_hashes[uid]
                        if new_hash != old_hashes[idx]:
                            users_to_update.append(user_tuple)
                            hashes_to_cache[f"user:hash:{uid}"] = new_hash

                # ================= 3. 数据库原子事务写入层 =================
                try:
                    async with self.pool.acquire() as conn:
                        async with conn.transaction():
                            # 3.1 写入/更新全局 users
                            if users_to_update:
                                await conn.executemany(self.UPSERT_USERS_SQL, sorted(users_to_update, key=lambda x: x[0]))

                            # 3.2 写入/更新极简版 cz_fans
                            if cz_fans_batch:
                                await conn.executemany(self.UPSERT_CZ_FANS_SQL, sorted(cz_fans_batch.values(), key=lambda x: x[0]))

                            # 3.3 根据类型路由具体流数据插入
                            if data_type == 'gift':
                                if specific_batch:
                                    await conn.executemany("""
                                        INSERT INTO live_gifts (web_rid, room_id, user_id, user_name, gift_id, gift_name, gift_icon,
                                        diamond_count, combo_count, group_count, total_diamond_count, pay_grade, pay_grade_icon, 
                                        fans_club_level, fans_club_icon, send_time, created_at) 
                                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17);
                                    """, specific_batch)
                                if room_updates:
                                    room_update_params = [(v['ticket'], v['diamond'], k) for k, v in sorted(room_updates.items(), key=lambda x: x[0])]
                                    await conn.executemany(
                                        "UPDATE rooms SET fans_ticket_count = fans_ticket_count + $1, total_diamond_count = total_diamond_count + $2, updated_at = CURRENT_TIMESTAMP WHERE room_id = $3", 
                                        room_update_params
                                    )
                            elif data_type == 'chat':
                                if specific_batch:
                                    await conn.executemany("""
                                        INSERT INTO live_chats (web_rid, room_id, user_id, user_name, content, pay_grade, pay_grade_icon, 
                                        fans_club_level, fans_club_icon, event_time, created_at) 
                                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11);
                                    """, specific_batch)
                                if room_updates:
                                    room_chat_params = [(v, k) for k, v in sorted(room_updates.items(), key=lambda x: x[0])]
                                    await conn.executemany(
                                        "UPDATE rooms SET total_chat_count = total_chat_count + $1, updated_at = CURRENT_TIMESTAMP WHERE room_id = $2", 
                                        room_chat_params
                                    )
                    
                    # 3.4 事务提交成功，批量刷新 Redis 状态标记
                    if hashes_to_cache or cz_active_cache_updates:
                        try:
                            pipe = redis_client.pipeline()
                            for k, v in hashes_to_cache.items(): pipe.set(k, v, ex=604800) # 基础信息 Hash 保存 7 天
                            for k, v in cz_active_cache_updates.items(): pipe.set(k, v, ex=7200) # 活跃期节流保存 2 小时
                            await pipe.execute()
                        except Exception: pass
                    
                    db_success = True
                except Exception as e:
                    logger.error(f"❌ [DB] 刷新 {data_type} 数据异常: {e}")

            # ================= 4. 收尾机制与指数退避 =================
            try:
                retry_attr = f'_{data_type}_retry_count'
                if db_success:
                    await redis_client.lpop(backup_key, count=len(raw_data_list))
                    setattr(self, retry_attr, 0)
                else:
                    _retry_count = getattr(self, retry_attr, 0) + 1
                    _backoff = min(self.FLUSH_BASE_BACKOFF * (2 ** (_retry_count - 1)), self.FLUSH_MAX_BACKOFF)
                    setattr(self, retry_attr, _retry_count)
                    
                    if _retry_count > self.FLUSH_MAX_RETRIES:
                        logger.error(f"🚨 [DB] {data_type} 批次连败 {_retry_count} 次，退回主队列等待")
                        await redis_client.lpop(backup_key, count=len(raw_data_list))
                        await redis_client.lpush(main_key, *raw_data_list[::-1])
                        setattr(self, retry_attr, 0)
                        break
                    else:
                        logger.warning(f"♻️ [DB] {data_type} 写入失败，{_backoff:.0f}s 后重试 ({_retry_count}/{self.FLUSH_MAX_RETRIES})")
                        await redis_client.lpop(backup_key, count=len(raw_data_list))
                        await redis_client.lpush(main_key, *raw_data_list[::-1])
                        
                        async def _delayed_retry():
                            await asyncio.sleep(_backoff)
                            if not self._shutting_down:
                                await self._flush_buffer_pipeline(data_type)
                                
                        if data_type == 'gift': self._flush_gift_task = asyncio.create_task(_delayed_retry())
                        else: self._flush_chat_task = asyncio.create_task(_delayed_retry())
                        break
            except Exception as e:
                logger.error(f"❌ [DB] 维护 {data_type} 备份队列异常: {e}")
                break

    # =========================================================================
    # 辅助业务方法
    # =========================================================================
    async def save_room_info(self, data: dict):
        if not data or 'room_id' not in data: return
        room_id = data.get('room_id')
        web_rid = data.get('web_rid', '')
        title = data.get('title', '')
        if title and len(title) > 255: title = title[:250] + "..."
            
        user_id = data.get('user_id', '')
        sec_uid = data.get('sec_uid', '')
        if sec_uid and len(sec_uid) > 255: sec_uid = sec_uid[:255]
            
        nickname = data.get('nickname', '')
        if nickname and len(nickname) > 128: nickname = nickname[:128]
            
        avatar_url = extract_filename(data.get('avatar_url', ''))
        live_status = data.get('live_status', 1)
        start_follower_count = data.get('start_follower_count', 0)
        
        sql = """
            INSERT INTO rooms (room_id, web_rid, title, user_id, sec_uid, nickname, avatar_url, live_status, room_status, start_follower_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, $9)
            ON CONFLICT (room_id) DO UPDATE SET
                web_rid = EXCLUDED.web_rid, title = EXCLUDED.title, nickname = EXCLUDED.nickname,
                avatar_url = EXCLUDED.avatar_url, live_status = EXCLUDED.live_status, room_status = EXCLUDED.room_status,
                updated_at = CURRENT_TIMESTAMP;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(sql, room_id, web_rid, title, user_id, sec_uid, nickname, avatar_url, live_status, start_follower_count)
        except Exception as e:
            logger.error(f"❌ [DB] 保存直播间信息失败: {e}")

    async def update_room_stats(self, room_id, stats: dict):
        if not room_id or not stats: return
        user_count = stats.get('user_count', -1)
        total_user = stats.get('total_user', 0)
        like_count = stats.get('like_count', 0)
        live_status = stats.get('live_status')
        
        sql = """
            UPDATE rooms SET
                user_count = CASE WHEN $2 >= 0 THEN $2 ELSE user_count END,
                total_user_count = GREATEST(total_user_count, $3),
                like_count = GREATEST(like_count, $4),
                max_viewers = CASE WHEN $2 >= 0 THEN GREATEST(max_viewers, $2) ELSE max_viewers END,
                live_status = CASE WHEN $5::int IS NOT NULL THEN $5 ELSE live_status END,
                room_status = CASE WHEN $5::int IS NOT NULL THEN $5 ELSE room_status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE room_id = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(sql, room_id, user_count, total_user, like_count, live_status)
        except Exception: pass 

    async def set_room_ended(self, room_id: str):
        if not room_id: return
        sql = """
            UPDATE rooms 
            SET live_status = 4, room_status = 4, end_time = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE room_id = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(sql, room_id)
            logger.info(f"🏁 [DB] 直播间 {room_id} 已标记为结束")
        except Exception as e: pass

    async def update_room_realtime(self, room_id: str, live_status: int, current_follower_count: int):
        if not room_id: return
        try:
            sql = """
                UPDATE rooms 
                SET updated_at = CURRENT_TIMESTAMP,
                    live_status = $2, 
                    room_status = $2,
                    current_follower_count = CASE WHEN $3 > 0 THEN $3 ELSE current_follower_count END,
                    follower_diff = CASE WHEN $3 > 0 AND start_follower_count > 0 THEN $3 - start_follower_count ELSE follower_diff END
                WHERE room_id = $1;
            """
            async with self.pool.acquire() as conn:
                await conn.execute(sql, room_id, live_status, current_follower_count)
        except Exception as e: pass

    async def save_author_card(self, data: dict):
        if not data or not data.get('sec_uid'): return
        try:
            sec_uid = data['sec_uid'][:255] if data['sec_uid'] else ''
            nickname = data.get('nickname', '')
            if nickname and len(nickname) > 128: nickname = nickname[:128]
            
            avatar = extract_filename(data.get('avatar', ''))
            web_rid = data.get('web_rid', '')
            self_web_rid = data.get('self_web_rid', '')
            live_status = data.get('live_status', 0)
            weight = data.get('weight', 0)
            user_count = data.get('user_count', 0)
            
            sql = """
                INSERT INTO authors (sec_uid, uid, web_rid, self_web_rid, nickname, avatar, follower_count, live_status, weight, user_count)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (sec_uid) DO UPDATE SET
                    uid = EXCLUDED.uid, web_rid = EXCLUDED.web_rid, 
                    self_web_rid = COALESCE(NULLIF(EXCLUDED.self_web_rid, ''), authors.self_web_rid),
                    nickname = EXCLUDED.nickname, avatar = EXCLUDED.avatar, 
                    follower_count = EXCLUDED.follower_count, live_status = EXCLUDED.live_status, 
                    weight = EXCLUDED.weight, user_count = EXCLUDED.user_count,
                    updated_at = CURRENT_TIMESTAMP;
            """
            async with self.pool.acquire() as conn:
                await conn.execute(sql, sec_uid, data.get('uid'), web_rid, self_web_rid, nickname, avatar, data.get('follower_count', 0), live_status, weight, user_count)
        except Exception as e: pass

    async def save_pk_result(self, pk_data: dict):
        if not pk_data: return
        try:
            teams_json = orjson.dumps(pk_data.get('teams', [])).decode('utf-8')
            sql = """
                INSERT INTO pk_history (battle_id, room_id, channel_id, mode, duration, start_time, teams, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                ON CONFLICT (battle_id, room_id) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id, mode = EXCLUDED.mode,
                    duration = EXCLUDED.duration, teams = EXCLUDED.teams; 
            """
            async with self.pool.acquire() as conn:
                await conn.execute(sql, pk_data['battle_id'], pk_data['room_id'], pk_data.get('channel_id'), 
                                   pk_data.get('mode'), pk_data.get('duration'), to_dt(pk_data.get('start_time')), 
                                   teams_json, to_dt(pk_data.get('created_at')))
        except Exception as e: pass

    async def increment_room_stats(self, room_id: str, inc_data: dict):
        if not room_id or not inc_data: return
        ALLOWED_KEYS = {
            'user_count', 'total_user_count', 'like_count', 
            'max_viewers', 'fans_ticket_count', 'total_diamond_count',
            'total_chat_count', 'total_watch_time_sec'
        }
        set_clauses, values = [], []
        i = 1
        for key, val in inc_data.items():
            if key not in ALLOWED_KEYS: continue
            set_clauses.append(f"{key} = {key} + ${i}")
            values.append(val)
            i += 1
            
        if not set_clauses: return 
        values.append(room_id) 
        set_str = ", ".join(set_clauses)
        
        sql = f"UPDATE rooms SET {set_str}, updated_at = CURRENT_TIMESTAMP WHERE room_id = ${len(values)}"
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(sql, *values)
        except Exception as e: pass

    async def get_room_live_status(self, room_id: str):
        try:
            sql = "SELECT live_status FROM rooms WHERE room_id = $1;"
            async with self.pool.acquire() as conn:
                res = await conn.fetchval(sql, room_id)
                return res if res is not None else 0
        except Exception: return 0

    async def get_all_cookies(self):
        try:
            sql = "SELECT cookie FROM settings_cookies WHERE status != 'expired';"
            async with self.pool.acquire() as conn:
                records = await conn.fetch(sql)
                return [r['cookie'] for r in records if r['cookie']]
        except Exception: return []

    async def add_cookie(self, cookie_str: str, note: str = ""):
        if not cookie_str: return
        cookie_hash = hashlib.md5(cookie_str.encode('utf-8')).hexdigest()
        try:
            sql = """
                INSERT INTO settings_cookies (cookie_hash, cookie, note, status)
                VALUES ($1, $2, $3, 'valid')
                ON CONFLICT (cookie_hash) DO UPDATE SET
                    cookie = EXCLUDED.cookie, status = 'valid', updated_at = CURRENT_TIMESTAMP;
            """
            async with self.pool.acquire() as conn:
                await conn.execute(sql, cookie_hash, cookie_str, note)
        except Exception: pass

    async def delete_cookie(self, cookie_str: str):
        if not cookie_str: return
        cookie_hash = hashlib.md5(cookie_str.encode('utf-8')).hexdigest()
        try:
            async with self.pool.acquire() as conn:
                check_sql = "SELECT note FROM settings_cookies WHERE cookie_hash = $1;"
                record = await conn.fetchrow(check_sql, cookie_hash)
                
                if record and record['note']:
                    update_sql = "UPDATE settings_cookies SET cookie = '', status = 'expired', updated_at = CURRENT_TIMESTAMP WHERE cookie_hash = $1;"
                    await conn.execute(update_sql, cookie_hash)
                else:
                    delete_sql = "DELETE FROM settings_cookies WHERE cookie_hash = $1;"
                    await conn.execute(delete_sql, cookie_hash)
        except Exception as e: pass
            
    async def clear_zombie_rooms(self, timeout_seconds=180):
        try:
            sql = """
                UPDATE rooms
                SET live_status = 4, room_status = 4, end_time = updated_at, end_reason = 'zombie_cleanup'
                WHERE live_status = 1 AND updated_at < CURRENT_TIMESTAMP - ($1 || ' seconds')::interval
                RETURNING room_id;
            """
            async with self.pool.acquire() as conn:
                records = await conn.fetch(sql, str(timeout_seconds))
                zombie_ids = [r['room_id'] for r in records]
            if zombie_ids: logger.warning(f"🧟‍♂️ [DB] 已清理僵尸房间: {zombie_ids}")
            return zombie_ids
        except Exception: return []

    async def upsert_vip_user(self, user_info: dict, web_rid: str = ""):
        if not user_info or not user_info.get('user_id') or self._shutting_down: return
        uid = user_info['user_id']
        current_cz_level = user_info.get('cz_club_level', 0)
        
        try:
            redis_client = get_redis()
            
            # ==========================================
            # 🛡️ 防线 1：判断专属活跃等级是否突破 (升级检测)
            # ==========================================
            cache_key = f"cz_active:{uid}"
            try:
                cached_val = await redis_client.get(cache_key)
                cached_level = int(cached_val) if cached_val is not None else -1
            except (ValueError, TypeError):
                cached_level = -1
                
            # 只有在陈泽房间，且 (从来没记录过 OR 发生了升级) 才允许写粉丝表
            is_cz_room = str(web_rid) == "615189692839" or current_cz_level > 0
            needs_cz_update = is_cz_room and (cached_level == -1 or current_cz_level > cached_level)

            # ==========================================
            # 🛡️ 防线 2：判断全局画像是否变化 (Hash 防抖)
            # ==========================================
            clean_avatar = extract_filename(user_info.get('avatar_url', ''))
            current_hash = self._get_user_fingerprint(
                uid, user_info.get('sec_uid', ''), user_info.get('display_id', ''),
                user_info.get('user_name', ''), user_info.get('gender', 0), 
                user_info.get('pay_grade', 0), clean_avatar
            )
            hash_key = f"user:hash:{uid}"
            try:
                old_hash = await redis_client.get(hash_key)
                if isinstance(old_hash, bytes): old_hash = old_hash.decode('utf-8')
            except Exception:
                old_hash = None
                
            needs_global_update = (current_hash != old_hash)

            # 🌟 如果等级没升，基础信息也没变，直接拦截，消灭无效的数据库直写！
            if not needs_cz_update and not needs_global_update:
                return

            # ==========================================
            # 💾 按需双写并更新缓存
            # ==========================================
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    if needs_global_update:
                        await conn.execute(self.UPSERT_USERS_SQL, uid, user_info.get('sec_uid', ''), user_info.get('display_id', ''),
                             user_info.get('user_name', ''), user_info.get('gender', 0), user_info.get('pay_grade', 0), clean_avatar)
                        try: await redis_client.setex(hash_key, 604800, current_hash)
                        except: pass

                    if needs_cz_update:
                        await conn.execute(self.UPSERT_CZ_FANS_SQL, uid, current_cz_level)
                        # 安全地将更高的等级打入缓存
                        try: await redis_client.setex(cache_key, 7200, str(current_cz_level))
                        except: pass

        except Exception as e:
            logger.error(f"❌ [DB] 独立更新 VIP 用户失败: {e}")

    async def close(self):
        self._shutting_down = True  
        logger.info("💾 正在等待写库任务收尾...")
        if self._flush_chat_task and not self._flush_chat_task.done(): await self._flush_chat_task
        if self._flush_gift_task and not self._flush_gift_task.done(): await self._flush_gift_task

        logger.info("🧹 开始彻底排空 Redis 遗留队列数据...")
        await self.flush_chat_buffer()
        await self.flush_gift_buffer()
        
        if self.pool: await self.pool.close()
        logger.info("👋 PostgreSQL 连接池已安全关闭")