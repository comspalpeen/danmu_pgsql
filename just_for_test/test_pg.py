import asyncio
import asyncpg
import sys

# ================= 配置区 =================
# 请将 '你的服务器IP' 替换为实际的 IP 地址
DB_CONFIG = {
    "user": "czlevel",
    "password": "gogogochufale",
    "database": "dy_live_data",
    "host": "139.196.142.3", 
    "port": 2077
}
# ==========================================

async def test_connection():
    conn = None
    print(f"🚀 正在尝试连接到 {DB_CONFIG['host']}:{DB_CONFIG['port']}...")
    
    try:
        # 建立连接
        conn = await asyncpg.connect(**DB_CONFIG)
        print("✅ 连接成功！")

        # 测试查询权限 (查询 users 表前 3 行)
        print("🔍 正在测试 SELECT 权限...")
        rows = await conn.fetch("SELECT user_id, user_name, cz_club_level FROM users LIMIT 3")
        
        if not rows:
            print("💡 连接正常，但 users 表中目前没有数据。")
        else:
            print(f"🎉 成功读取到 {len(rows)} 条数据:")
            for row in rows:
                print(f"   - ID: {row['user_id']} | 昵称: {row['user_name']} | 等级: {row['cz_club_level']}")

        # 测试写入权限 (预期应该报错，因为是只读账户)
        print("\n🛡️ 正在验证只读限制 (预期会报错)...")
        try:
            await conn.execute("UPDATE users SET cz_club_level = 99 WHERE user_id = $1", rows[0]['user_id'])
            print("⚠️ 警告：只读账户竟然拥有写入权限！请检查授权。")
        except asyncpg.exceptions.InsufficientPrivilegeError:
            print("✅ 验证成功：该账户无法写入数据（权限不足），符合预期。")

    except asyncpg.exceptions.InvalidAuthorizationSpecificationError:
        print("❌ 报错：用户名或密码错误。")
    except asyncpg.exceptions.PostgresError as e:
        # 这里会捕获到你之前的 pg_hba.conf 错误
        print(f"❌ 数据库报错: {e}")
    except Exception as e:
        print(f"❌ 系统/网络错误: {e}")
    finally:
        if conn:
            await conn.close()
            print("\n👋 已断开连接。")

if __name__ == "__main__":
    try:
        asyncio.run(test_connection())
    except KeyboardInterrupt:
        pass