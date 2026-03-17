import asyncio
import asyncpg

# 你的 100 名目标用户名单（严格保持原序）
TARGET_USERS = [
    "斩虍", "Flechazooo", "高家小院—总部", "Czcz", "邻家小丈夫", "ꔷ w ꔷ", "珑·Yeps♾️（白门永存）", "蜡笔小葵", "𝓥𝓥", "coke老师",
    "抱住冬天", "wHZz-", "憋管我了", "宝贝", "碗糕", "M_Z", "吃冻梨硌了牙", "ACACAC", "羲驭", "玛法",
    "zxz", "Aila（三角洲行动）", "Slam)", "WENOVERLXRD", "A龙鸣集团-紀伯倫", "𝙎𝙚𝙖 .", "荒野一条狗", "涵", "珑·Cup☆", "2nite",
    "ranran⛓️", "HywEn^", "笙笙.", "小万（攒钱买机票回国）", "珠玉", "树上岛", "RachelCutieCookiePie", "皮皮-", "uriyyyy", "养一一一一",
    "推开世界的门☀️🌻", "想喝娃哈哈。", "Deku", "33", "7ine", "无糖可乐", "萌子", "Kaaaaaaz", "稚清", "DJ Aisa",
    "再回首已无影", "用户8977787079919", "ovo", "7iY.", "困困巧乐兹🎀", "MengKing(逆战未来)", "_在吃饺子", "夏虫", "幻听", "鳄鱼",
    "16_", "珂珂控", "zzzl", "michi3", "小念-", "ee.", "ttzi8one", "y", "tuotuo（无畏契约）", "cr1p1",
    "iiis.", "可达鸭鸭鸭", "里里LiLi", "聚高", "玻璃小羊", "果冻很肥（代✂️）", "博的游戏屋", "绪山", "小之妹妹", "Rx",
    "小猪🎉", "小兔写立可白❄️", "AKA大壁虎🦎", "美德宝宝", "鲲鲲鲲鲲困", "耶夢伽得", "⁺✞ʚ海底捞重度依赖ɞ✟₊", "X", "门门-🚢", "婷在庭",
    "四瓶真果粒", "iduce1.77", "我是真的想啸啊-🍑", "梅梅小西", "Allen.", "凶残冰7凌", "👾 Conan", "早春的树.", "🍗", "Ilbaml."
]

async def generate_report():
    pg_dsn = "postgresql://postgres:chufale@localhost:2077/dy_live_data"
    print("🔌 正在连接数据库并匹配特定时间段的消费数据...")
    
    # 核心修改：将时间条件放在 LEFT JOIN 的 ON 子句中，确保即使未在该时间段消费，也能查出 sec_uid
    sql = """
        SELECT 
            u.user_name,
            MAX(u.sec_uid) AS sec_uid,
            COALESCE(SUM(g.total_diamond_count), 0) AS total_diamonds
        FROM users u
        LEFT JOIN live_gifts g 
            ON u.user_id = g.user_id 
           AND g.send_time >= '2026-03-02 22:30:00' 
           AND g.send_time <= '2026-03-02 22:41:00'
        WHERE u.user_name = ANY($1::varchar[])
        GROUP BY u.user_name;
    """
    
    try:
        pool = await asyncpg.create_pool(dsn=pg_dsn)
        async with pool.acquire() as conn:
            records = await conn.fetch(sql, TARGET_USERS)
        await pool.close()
    except Exception as e:
        print(f"❌ 数据库查询失败: {e}")
        return

    # 将数据库结果转为字典，方便 O(1) 查找
    db_data = {}
    for r in records:
        db_data[r['user_name']] = {
            'sec_uid': r['sec_uid'],
            'diamonds': r['total_diamonds']
        }

    # ================= 组装移动端友好的 HTML =================
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>区间消费匹配清单</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f2f2f6; margin: 0; padding: 20px 10px; color: #1c1c1e; }
            .container { max-width: 480px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); overflow: hidden; }
            .header { background: linear-gradient(135deg, #ff2a5f, #ff7b9a); color: white; text-align: center; padding: 20px 15px; }
            .header h2 { margin: 0; font-size: 20px; font-weight: 600; letter-spacing: 1px; }
            .header p { margin: 8px 0 0 0; font-size: 12px; opacity: 0.95; background: rgba(0,0,0,0.15); display: inline-block; padding: 4px 10px; border-radius: 12px; }
            .list-item { display: flex; align-items: center; padding: 15px; border-bottom: 1px solid #f0f0f0; transition: background-color 0.2s; }
            .list-item:last-child { border-bottom: none; }
            .list-item:hover { background-color: #f9f9f9; }
            .idx { width: 30px; font-size: 14px; color: #8e8e93; font-weight: bold; }
            .info { flex-grow: 1; overflow: hidden; padding-right: 10px; }
            .name { font-size: 15px; font-weight: 500; color: #000; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; }
            .diamonds { font-size: 13px; color: #ff2a5f; font-weight: 600; display: flex; align-items: center; }
            .diamonds::before { content: "💎"; margin-right: 4px; font-size: 12px; }
            .action a { display: inline-block; padding: 6px 12px; background-color: #f2f2f6; color: #007aff; text-decoration: none; border-radius: 16px; font-size: 12px; font-weight: 500; }
            .action a:active { background-color: #e5e5ea; }
            .action a.disabled { color: #aeaeb2; pointer-events: none; background-color: #f2f2f6; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>核心用户区间账单</h2>
                <p>🕒 2026-03-02 22:30 ~ 22:41</p>
            </div>
    """

    for idx, name in enumerate(TARGET_USERS, 1):
        user_info = db_data.get(name, {'sec_uid': None, 'diamonds': 0})
        diamonds = user_info['diamonds']
        sec_uid = user_info['sec_uid']
        
        diamond_str = f"{diamonds:,}" if diamonds > 0 else "0"
        
        if sec_uid:
            link_html = f'<a href="https://www.douyin.com/user/{sec_uid}" target="_blank">主页</a>'
        else:
            link_html = '<a href="#" class="disabled">暂无</a>'
            
        html_content += f"""
            <div class="list-item">
                <div class="idx">{idx}</div>
                <div class="info">
                    <div class="name">{name}</div>
                    <div class="diamonds">{diamond_str}</div>
                </div>
                <div class="action">
                    {link_html}
                </div>
            </div>
        """

    html_content += """
        </div>
    </body>
    </html>
    """

    filename = "top100_users_report_sliced.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"✅ 生成完毕！成功处理区间消费数据。")
    print(f"📱 请打开 {filename} 查看，已标注过滤时间段！")

if __name__ == "__main__":
    asyncio.run(generate_report())