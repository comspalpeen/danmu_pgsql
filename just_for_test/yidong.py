import asyncio
import asyncpg
import logging
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Migration")

# 你的数据库连接串 (直接从你的 db.py 中提取)
DSN = "postgresql://postgres:chufale@127.0.0.1:2077/dy_live_data"
# 陈泽直播间的 web_rid
TARGET_WEB_RID = "615189692839"

async def run_migration():
    logger.info("🚀 开始启动陈泽直播间粉丝团等级(cz_club_level)历史数据迁移任务...")
    start_time = time.time()
    
    try:
        # 连接数据库
        conn = await asyncpg.connect(DSN)
        logger.info("✅ 数据库连接成功！")

        # ==========================================
        # 第一步：创建临时索引加速查询
        # ==========================================
        logger.info("⏳ 正在为 live_gifts 和 live_chats 创建临时复合索引 (这可能需要几分钟，请耐心等待)...")
        
        await conn.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tmp_gifts_migration 
            ON live_gifts (web_rid, user_id, fans_club_level);
        """)
        logger.info("✅ live_gifts 临时索引创建完成！")
        
        await conn.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tmp_chats_migration 
            ON live_chats (web_rid, user_id, fans_club_level);
        """)
        logger.info("✅ live_chats 临时索引创建完成！")

        # ==========================================
        # 第二步：执行聚合查询与数据更新
        # ==========================================
        logger.info("⏳ 正在计算历史最高等级并同步至 users 表 (核心更新中)...")
        
        # SQL 逻辑说明：
        # 1. 使用 UNION ALL 把礼物表和弹幕表中陈泽直播间的数据合并（过滤掉等级为0的数据）
        # 2. 按 user_id 分组，选出 MAX(fans_club_level)
        # 3. 将结果与 users 表关联，使用 GREATEST 保留最大值
        # 4. 加入条件 m.max_level > u.cz_club_level，只更新那些确实需要升级的行，大幅减少磁盘 I/O
        update_sql = f"""
            WITH combined_fans AS (
                SELECT user_id, fans_club_level 
                FROM live_gifts 
                WHERE web_rid = '{TARGET_WEB_RID}' AND fans_club_level > 0
                UNION ALL
                SELECT user_id, fans_club_level 
                FROM live_chats 
                WHERE web_rid = '{TARGET_WEB_RID}' AND fans_club_level > 0
            ),
            max_fans AS (
                SELECT user_id, MAX(fans_club_level) as max_level
                FROM combined_fans
                GROUP BY user_id
            )
            UPDATE users u
            SET 
                cz_club_level = GREATEST(COALESCE(u.cz_club_level, 0), m.max_level),
                updated_at = CURRENT_TIMESTAMP
            FROM max_fans m
            WHERE u.user_id = m.user_id
            AND m.max_level > COALESCE(u.cz_club_level, 0);
        """
        
        result = await conn.execute(update_sql)
        # asyncpg 的 execute 返回类似 "UPDATE 15203" 的字符串，我们可以从中提取更新的行数
        updated_rows = result.split()[-1] if result.startswith("UPDATE") else "0"
        logger.info(f"🎉 核心数据迁移完毕！共成功更新 {updated_rows} 位观众的 cz_club_level 字段。")

        # ==========================================
        # 第三步：清理临时索引 (过河拆桥)
        # ==========================================
        logger.info("🧹 正在清理临时索引...")
        await conn.execute("DROP INDEX IF EXISTS idx_tmp_gifts_migration;")
        await conn.execute("DROP INDEX IF EXISTS idx_tmp_chats_migration;")
        logger.info("✅ 临时索引清理完毕！")

    except Exception as e:
        logger.error(f"❌ 迁移过程中发生致命错误: {e}", exc_info=True)
        # 发生错误时尝试清理可能残留的索引
        try:
            logger.info("🚑 尝试紧急清理临时索引...")
            await conn.execute("DROP INDEX IF EXISTS idx_tmp_gifts_migration;")
            await conn.execute("DROP INDEX IF EXISTS idx_tmp_chats_migration;")
        except Exception:
            pass
    finally:
        # 关闭连接
        if 'conn' in locals() and not conn.is_closed():
            await conn.close()
            
        elapsed = time.time() - start_time
        logger.info(f"🛑 迁移任务全部结束！总耗时: {elapsed:.2f} 秒。")

if __name__ == "__main__":
    # 确保在 Windows/Linux 下都能正常运行 asyncio
    asyncio.run(run_migration())