# clean_wandering_users.py
import asyncio
import asyncpg
from datetime import datetime

# 替换为你的真实数据库连接串
DSN = "postgresql://postgres:chufale@127.0.0.1:2077/dy_live_data" 

# 👇 在这里设置你意外开启无关直播的准确时间段
START_TIME = '2026-04-17 12:00:00'
END_TIME = '2026-04-17 18:05:00'

async def main():
    conn = await asyncpg.connect(DSN)
    
    # 核心查询条件：时间范围内，且在三个关联表中都不存在
    query_base = """
        FROM users u
        WHERE u.updated_at >= $1 AND u.updated_at <= $2
          AND NOT EXISTS (SELECT 1 FROM live_chats c WHERE c.user_id = u.user_id)
          AND NOT EXISTS (SELECT 1 FROM live_gifts g WHERE g.user_id = u.user_id)
          AND NOT EXISTS (SELECT 1 FROM cz_fans cz WHERE cz.user_id = u.user_id)
    """
    
    start_dt = datetime.strptime(START_TIME, '%Y-%m-%d %H:%M:%S')
    end_dt = datetime.strptime(END_TIME, '%Y-%m-%d %H:%M:%S')

    print("🔍 正在扫描游离用户，请稍候...")
    
    # 1. 先计算数量
    count_sql = f"SELECT count(*) {query_base}"
    count = await conn.fetchval(count_sql, start_dt, end_dt)
    
    print(f"📊 在 {START_TIME} 到 {END_TIME} 期间，发现了 【{count}】 个符合条件的游离用户。")

    # 2. 用户确认后执行删除
    if count > 0:
        choice = input("⚠️ 是否确认永久删除这些用户？(y/n): ")
        if choice.lower() == 'y':
            delete_sql = f"DELETE {query_base}"
            result = await conn.execute(delete_sql, start_dt, end_dt)
            print(f"✅ 清理完成！数据库返回信息: {result}")
        else:
            print("🚫 已取消删除操作。")
    else:
        print("🎉 没有找到需要清理的游离用户。")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())