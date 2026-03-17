import asyncio
import asyncpg
import logging
import time

# 配置日志，让你看得清清楚楚
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Cleaner")

# 你的数据库连接配置
DSN = "postgresql://postgres:chufale@127.0.0.1:2077/dy_live_data"
# 你要清理的特定场次 room_id
TARGET_ROOM_ID = '7612240511935515442'

async def clean_room_data():
    logger.info(f"🚀 开始精准清理直播间 {TARGET_ROOM_ID} 的所有数据...")
    start_time = time.time()
    
    try:
        conn = await asyncpg.connect(DSN)
        logger.info("✅ 数据库连接成功！")

        # 使用事务保护，要么全成功，要么全不删，绝对不留半吊子垃圾
        async with conn.transaction():
            
            # ==========================================
            # 第一步：锁定嫌疑人 (找出这个直播间所有发言/送礼的用户)
            # ==========================================
            logger.info("🔍 正在扫描该场直播的交互用户名单...")
            users_records = await conn.fetch('''
                SELECT DISTINCT user_id FROM live_chats WHERE room_id = $1
                UNION
                SELECT DISTINCT user_id FROM live_gifts WHERE room_id = $1
            ''', TARGET_ROOM_ID)
            
            target_users = [r['user_id'] for r in users_records]
            logger.info(f"🎯 扫描完毕：该直播间共有 {len(target_users)} 名独立用户参与互动。")

            # ==========================================
            # 第二步：大扫除 (删除该直播间的弹幕、礼物、PK、房间信息)
            # ==========================================
            logger.info("🧹 开始清理该直播间的业务数据...")
            
            res_chats = await conn.execute("DELETE FROM live_chats WHERE room_id = $1", TARGET_ROOM_ID)
            # asyncpg 的 execute 返回值类似 "DELETE 1520"，我们提取最后的数字
            logger.info(f"   -> 🗑️ 弹幕清理完毕：共删除 {res_chats.split()[-1]} 条。")

            res_gifts = await conn.execute("DELETE FROM live_gifts WHERE room_id = $1", TARGET_ROOM_ID)
            logger.info(f"   -> 🗑️ 礼物清理完毕：共删除 {res_gifts.split()[-1]} 条。")

            res_pk = await conn.execute("DELETE FROM pk_history WHERE room_id = $1", TARGET_ROOM_ID)
            logger.info(f"   -> 🗑️ PK记录清理完毕：共删除 {res_pk.split()[-1]} 条。")

            res_rooms = await conn.execute("DELETE FROM rooms WHERE room_id = $1", TARGET_ROOM_ID)
            logger.info(f"   -> 🗑️ 房间信息清理完毕：共删除 {res_rooms.split()[-1]} 条。")

            # ==========================================
            # 第三步：精准超度 (找出只看他的专属粉丝并清理)
            # ==========================================
            if target_users:
                logger.info("🕵️‍♂️ 正在比对这批用户的全网记录，筛选孤儿用户 (专属粉丝)...")
                # 用 PostgreSQL 的 unnest 将 Python 数组转为虚拟表进行极速比对
                orphans = await conn.fetch('''
                    SELECT u.user_id 
                    FROM unnest($1::text[]) AS u(user_id)
                    WHERE NOT EXISTS (SELECT 1 FROM live_chats c WHERE c.user_id = u.user_id)
                      AND NOT EXISTS (SELECT 1 FROM live_gifts g WHERE g.user_id = u.user_id)
                ''', target_users)
                
                orphan_ids = [r['user_id'] for r in orphans]
                logger.info(f"⚖️ 鉴定结果：{len(target_users)} 人中，有 {len(orphan_ids)} 人是该主播专属粉丝，其余均去过其他直播间。")

                if orphan_ids:
                    # 批量删除这些专属粉丝的 users 表记录
                    res_users = await conn.execute("DELETE FROM users WHERE user_id = ANY($1::text[])", orphan_ids)
                    logger.info(f"💥 拔草除根：成功将 {res_users.split()[-1]} 名专属粉丝从 users 表彻底移除！")
                else:
                    logger.info("👌 没有发现专属粉丝，不需要从 users 表中删人。")
            else:
                logger.info("🤷‍♂️ 这个直播间没有任何用户互动记录，跳过用户比对。")

        logger.info("🎉 事务提交成功，所有清理操作已完美生效！")

    except Exception as e:
        logger.error(f"❌ 清理过程中发生异常，所有操作已自动回滚，数据安全: {e}", exc_info=True)
    finally:
        if 'conn' in locals() and not conn.is_closed():
            await conn.close()
        logger.info(f"🛑 脚本执行结束，总耗时: {time.time() - start_time:.2f} 秒。")

if __name__ == "__main__":
    asyncio.run(clean_room_data())