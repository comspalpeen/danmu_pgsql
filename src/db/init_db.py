# init_db.py
import asyncio
import asyncpg
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("InitDB")

# 你的数据库连接配置
import os
from dotenv import load_dotenv

# Load .env from the root directory of the project
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path)
from pathlib import Path

# 获取当前脚本的绝对路径的父目录的父目录的父目录 (src/db/init_db.py -> src/db -> src -> 根目录)
root_dir = Path(__file__).resolve().parent.parent.parent
dotenv_path = root_dir / '.env'

load_dotenv(dotenv_path)
DSN = os.environ.get("PG_DSN")
if not DSN:
    raise ValueError("PG_DSN is not set in the .env file.")

async def init_tables(pool):
    """初始化 PostgreSQL 基础表"""
    # 🌟 核心修改：首先确保启用 citext 扩展
    ext_sql = "CREATE EXTENSION IF NOT EXISTS citext;"
    # 🌟 修改 1：在 users 表中补齐 display_id 字段
    users_ddl = """
    CREATE TABLE IF NOT EXISTS users (
        user_id VARCHAR(64) PRIMARY KEY,
        sec_uid VARCHAR(255),
        display_id CITEXT,  -- 改为 CITEXT
        user_name VARCHAR(128) NOT NULL,
        gender SMALLINT DEFAULT 0,
        pay_grade SMALLINT DEFAULT 0,
        avatar_url VARCHAR(255),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    # 🌟 修改 2：新增专属极简粉丝表
    cz_fans_ddl = """
    CREATE TABLE IF NOT EXISTS cz_fans (
        user_id VARCHAR(64) PRIMARY KEY,
        cz_club_level INTEGER DEFAULT 0,
        last_active_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    chats_ddl = """
    CREATE TABLE IF NOT EXISTS live_chats (
        id BIGSERIAL PRIMARY KEY,
        web_rid VARCHAR(64),
        room_id VARCHAR(64) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        user_name VARCHAR(128),
        content TEXT NOT NULL,
        pay_grade SMALLINT DEFAULT 0,
        pay_grade_icon VARCHAR(128),
        fans_club_level SMALLINT DEFAULT 0,
        fans_club_icon VARCHAR(128),
        event_time TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    gifts_ddl = """
    CREATE TABLE IF NOT EXISTS live_gifts (
        id BIGSERIAL PRIMARY KEY,
        web_rid VARCHAR(64),
        room_id VARCHAR(64) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        user_name VARCHAR(128),
        gift_id VARCHAR(64),
        gift_name VARCHAR(64),
        gift_icon VARCHAR(128),
        diamond_count INTEGER DEFAULT 0,
        combo_count INTEGER DEFAULT 1,
        group_count INTEGER DEFAULT 1,
        total_diamond_count INTEGER DEFAULT 0,
        pay_grade SMALLINT DEFAULT 0,
        pay_grade_icon VARCHAR(128),
        fans_club_level SMALLINT DEFAULT 0,
        fans_club_icon VARCHAR(128),
        send_time TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    rooms_ddl = """
    CREATE TABLE IF NOT EXISTS rooms (
        room_id VARCHAR(64) PRIMARY KEY,
        web_rid VARCHAR(64),
        title VARCHAR(255),
        user_id VARCHAR(64),
        sec_uid VARCHAR(255),
        nickname VARCHAR(128),
        avatar_url VARCHAR(255),
        user_count INTEGER DEFAULT 0,
        total_user_count INTEGER DEFAULT 0,
        like_count INTEGER DEFAULT 0,
        total_diamond_count INTEGER DEFAULT 0,
        total_chat_count INTEGER DEFAULT 0,
        max_viewers INTEGER DEFAULT 0,
        fans_ticket_count INTEGER DEFAULT 0,
        total_watch_time_sec BIGINT DEFAULT 0,
        live_status SMALLINT DEFAULT 0,
        room_status SMALLINT DEFAULT 0,
        start_follower_count INTEGER DEFAULT 0,
        current_follower_count INTEGER DEFAULT 0,
        follower_diff INTEGER DEFAULT 0,
        end_time TIMESTAMP,
        end_reason VARCHAR(64),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    authors_ddl = """
    CREATE TABLE IF NOT EXISTS authors (
        sec_uid VARCHAR(255) PRIMARY KEY,
        uid VARCHAR(64),
        web_rid VARCHAR(64),
        self_web_rid VARCHAR(64),
        nickname VARCHAR(128),
        avatar VARCHAR(255),
        follower_count INTEGER DEFAULT 0,
        user_count INTEGER DEFAULT 0,
        live_status SMALLINT DEFAULT 0,
        weight INTEGER DEFAULT 0,
        guild VARCHAR(128),
        common_name VARCHAR(128),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    pk_history_ddl = """
    CREATE TABLE IF NOT EXISTS pk_history (
        battle_id VARCHAR(64),
        room_id VARCHAR(64),
        channel_id VARCHAR(64),
        mode VARCHAR(64),
        duration VARCHAR(64),
        start_time TIMESTAMP,
        teams JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (battle_id, room_id)
    );
    """
    
    daily_reports_ddl = """
    CREATE TABLE IF NOT EXISTS daily_reports (
        date DATE,
        uid VARCHAR(64),
        nickname VARCHAR(128),
        avatar_url VARCHAR(255),
        pay_grade_icon VARCHAR(255),
        pay_grade_level SMALLINT DEFAULT 0,
        follower_count INTEGER DEFAULT 0,
        active_fans_count INTEGER DEFAULT 0,
        total_fans_club INTEGER DEFAULT 0,
        today_new_fans INTEGER DEFAULT 0,
        task_1_completed INTEGER DEFAULT 0,
        PRIMARY KEY (date, uid)
    );
    """

# === API 专属扩展表 ===
    favorite_streamers_ddl = """
    CREATE TABLE IF NOT EXISTS favorite_streamers (
        sec_uid VARCHAR(255) PRIMARY KEY,
        nickname VARCHAR(128),
        avatar_url VARCHAR(255),
        group_name VARCHAR(64) DEFAULT '默认分组',
        display_id CITEXT, -- 改为 CITEXT
        grade_icon_url VARCHAR(255),
        follower_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

  #  check_presets_ddl = """
  #  CREATE TABLE IF NOT EXISTS check_presets (
 #       sec_uid VARCHAR(255) PRIMARY KEY,
 #       nickname VARCHAR(128),
  #      avatar_url VARCHAR(255),
  #      "group" VARCHAR(64) DEFAULT '默认分组',
  #      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  #  );
  #  """

    site_qna_ddl = """
    CREATE TABLE IF NOT EXISTS site_qna (
        id SERIAL PRIMARY KEY,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        "order" INTEGER DEFAULT 0,
        is_visible BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    settings_cookies_ddl = """
    CREATE TABLE IF NOT EXISTS settings_cookies (
        cookie_hash VARCHAR(32) PRIMARY KEY,
        cookie TEXT NOT NULL,
        note VARCHAR(255),
        status VARCHAR(32) DEFAULT 'valid',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    high_level_fans_ddl = """
    CREATE TABLE IF NOT EXISTS high_level_fans (
    user_id VARCHAR(64) PRIMARY KEY,
    sec_uid VARCHAR(255),
    display_id VARCHAR(128),
    nickname VARCHAR(128),
    avatar_url TEXT,
    club_level SMALLINT DEFAULT 0,
    intimacy BIGINT DEFAULT 0,
    participate_time BIGINT DEFAULT 0,
    pay_grade SMALLINT DEFAULT 0,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(ext_sql)
            await conn.execute(users_ddl)
            await conn.execute(cz_fans_ddl)  # 🌟 执行新表创建
            await conn.execute(chats_ddl)
            await conn.execute(gifts_ddl)
            await conn.execute(rooms_ddl)
            await conn.execute(authors_ddl)
            await conn.execute(pk_history_ddl)
            await conn.execute(daily_reports_ddl)
            await conn.execute(favorite_streamers_ddl)
           # await conn.execute(check_presets_ddl)
            await conn.execute(site_qna_ddl)
            await conn.execute(settings_cookies_ddl)
            await conn.execute(high_level_fans_ddl)
        logger.info("✅ 数据库表结构 (DDL) 创建完成")
    except Exception as e:
        logger.error(f"❌ 初始化数据库表失败: {e}")

async def init_indexes(pool):
    """核心业务表的高性能索引构建 (容错版)"""
    index_sqls = [
        # 弹幕表
        "CREATE INDEX IF NOT EXISTS idx_chats_room_time ON live_chats (room_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_chats_created_at ON live_chats (created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_chats_user_id ON live_chats (user_id);",
        # 礼物表
        "CREATE INDEX IF NOT EXISTS idx_gifts_room_time ON live_gifts (room_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_gifts_created_at ON live_gifts (created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_gifts_user_id ON live_gifts (user_id);",
        "CREATE INDEX IF NOT EXISTS idx_gifts_room_send_time ON live_gifts (room_id, send_time DESC);",
        
        # 房间表 
        "CREATE INDEX IF NOT EXISTS idx_rooms_user_id_time ON rooms (user_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_rooms_created_at ON rooms (created_at DESC);",
        
        # PK表
        "CREATE INDEX IF NOT EXISTS idx_pk_room_time ON pk_history (room_id, created_at DESC);",
        
        # 主播
        "CREATE INDEX IF NOT EXISTS idx_authors_nickname ON authors (nickname);",
        "CREATE INDEX IF NOT EXISTS idx_authors_guild ON authors (guild);",
        
        # 用户表
        "CREATE INDEX IF NOT EXISTS idx_users_sec_uid ON users (sec_uid);",
        "CREATE INDEX IF NOT EXISTS idx_users_display_id ON users (display_id);", # 🌟 修改 3：为外网查询 API 提供极速响应索引
        "CREATE INDEX IF NOT EXISTS idx_users_lower_user_name ON users (LOWER(user_name) varchar_pattern_ops);",
        
        # 日报表
        "CREATE INDEX IF NOT EXISTS idx_daily_reports_uid_date ON daily_reports (uid, date DESC);"
        #高等级表
        "CREATE INDEX IF NOT EXISTS idx_hlf_intimacy ON high_level_fans (intimacy DESC);",
        "CREATE INDEX IF NOT EXISTS idx_hlf_sec_uid ON high_level_fans (sec_uid);"
        #陈泽等级表
        "CREATE INDEX cz_fans_last_active_time_idx ON public.cz_fans (last_active_time);",
        "CREATE INDEX cz_fans_cz_club_level_idx ON public.cz_fans (cz_club_level);"
        
    ]
    
    success_count = 0
    try:
        async with pool.acquire() as conn:
            for sql in index_sqls:
                try:
                    await conn.execute(sql)
                    success_count += 1
                except Exception as sub_e:
                    logger.warning(f"⚠️ 跳过某条索引构建 (可能是字段名不一致) -> {sub_e}")
                    
        logger.info(f"✅ 数据库核心索引构建流程结束 (成功: {success_count}/{len(index_sqls)})")
    except Exception as e:
        logger.error(f"❌ 索引构建外层异常: {e}")

async def main():
    logger.info("🚀 正在连接数据库准备执行初始化...")
    try:
        pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=2)
        await init_tables(pool)
        await init_indexes(pool)
        await pool.close()
        logger.info("🎉 数据库所有表和索引初始化全部完成！")
    except Exception as e:
        logger.error(f"❌ 连接数据库失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
