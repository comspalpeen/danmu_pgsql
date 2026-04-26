# delete_streamer_data.py
import asyncio
import asyncpg
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Cleaner")

# 替换为你的真实数据库连接串
DSN = "postgres://user:password@localhost:5432/your_db" 

# 👇 在这里填写你要删除的主播的 web_rid (千万别填错成陈泽的 615189692839)
TARGET_WEB_RID = "1234567890"  

async def main():
    if TARGET_WEB_RID == "615189692839":
        logger.error("🚨 警告：检测到目标为陈泽的 web_rid，脚本拒绝执行！")
        return

    conn = await asyncpg.connect(DSN)
    
    logger.info(f"🔍 正在扫描主播 [web_rid: {TARGET_WEB_RID}] 的关联数据...")

    # 1. 精准锁定即将游离的用户 (核心查询)
    # 逻辑：找出在这个房间发过言/礼物的集合，减去 (在其他房间发过言/礼物的集合 + 陈泽粉丝集合)
    wandering_users_sql = """
        WITH TargetUsers AS (
            SELECT user_id FROM live_chats WHERE web_rid = $1
            UNION
            SELECT user_id FROM live_gifts WHERE web_rid = $1
        ),
        SafeUsers AS (
            SELECT user_id FROM live_chats WHERE web_rid != $1
            UNION
            SELECT user_id FROM live_gifts WHERE web_rid != $1
            UNION
            SELECT user_id FROM cz_fans
        ),
        UsersToDelete AS (
            SELECT user_id FROM TargetUsers
            EXCEPT
            SELECT user_id FROM SafeUsers
        )
        SELECT user_id FROM UsersToDelete;
    """
    
    users_to_delete_records = await conn.fetch(wandering_users_sql, TARGET_WEB_RID)
    user_ids_to_delete = [r['user_id'] for r in users_to_delete_records]
    user_delete_count = len(user_ids_to_delete)

    # 2. 统计其他表的待删除数量
    chats_count = await conn.fetchval("SELECT count(*) FROM live_chats WHERE web_rid = $1", TARGET_WEB_RID)
    gifts_count = await conn.fetchval("SELECT count(*) FROM live_gifts WHERE web_rid = $1", TARGET_WEB_RID)
    rooms_count = await conn.fetchval("SELECT count(*) FROM rooms WHERE web_rid = $1", TARGET_WEB_RID)
    authors_count = await conn.fetchval("SELECT count(*) FROM authors WHERE web_rid = $1", TARGET_WEB_RID)
    
    # pk_history 没有 web_rid，需要通过 rooms 表联查
    pks_count = await conn.fetchval("""
        SELECT count(*) FROM pk_history 
        WHERE room_id IN (SELECT room_id FROM rooms WHERE web_rid = $1)
    """, TARGET_WEB_RID)

    # 3. 输出报告并等待人工确认
    print("\n" + "="*50)
    print(f"📊 待清理数据报告 (主播 web_rid: {TARGET_WEB_RID})")
    print("="*50)
    print(f"👥 即将变成游离的用户数: {user_delete_count} 个")
    print(f"💬 关联弹幕记录数:       {chats_count} 条")
    print(f"🎁 关联礼物记录数:       {gifts_count} 条")
    print(f"⚔️  关联 PK 记录数:       {pks_count} 场")
    print(f"🏠 关联直播间记录数:     {rooms_count} 个")
    print(f"👤 主播画像 (authors):   {authors_count} 个")
    print("="*50 + "\n")

    total_records = user_delete_count + chats_count + gifts_count + pks_count + rooms_count + authors_count
    if total_records == 0:
        logger.info("🎉 数据库中没有找到该主播的任何相关记录，无需清理。")
        await conn.close()
        return

    choice = input("⚠️ 是否确认在【单次原子事务】中永久删除以上所有数据？(y/n): ")
    if choice.lower() != 'y':
        logger.info("🚫 已取消删除操作，数据未做任何更改。")
        await conn.close()
        return

    # 4. 执行原子事务级删除 (防中断断点)
    logger.info("🗑️ 正在执行原子删除，期间如果断开会自动回滚...")
    try:
        async with conn.transaction():
            # 删游离用户 (如果列表不为空)
            if user_ids_to_delete:
                await conn.execute("DELETE FROM users WHERE user_id = ANY($1::varchar[])", user_ids_to_delete)
            
            # 删弹幕和礼物
            await conn.execute("DELETE FROM live_chats WHERE web_rid = $1", TARGET_WEB_RID)
            await conn.execute("DELETE FROM live_gifts WHERE web_rid = $1", TARGET_WEB_RID)
            
            # 删 PK 记录 (依赖 rooms 表，所以必须在删 rooms 之前执行)
            await conn.execute("""
                DELETE FROM pk_history 
                WHERE room_id IN (SELECT room_id FROM rooms WHERE web_rid = $1)
            """, TARGET_WEB_RID)
            
            # 删房间和主播本体
            await conn.execute("DELETE FROM rooms WHERE web_rid = $1", TARGET_WEB_RID)
            await conn.execute("DELETE FROM authors WHERE web_rid = $1", TARGET_WEB_RID)

        logger.info("✅ 所有关联数据已彻底清理完毕！")
    except Exception as e:
        logger.error(f"❌ 删除过程中发生异常，事务已自动回滚，数据未受损: {e}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())