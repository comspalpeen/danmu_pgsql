import asyncio
import asyncpg

async def export_html():
    pg_dsn = "postgresql://postgres:chufale@localhost:2077/dy_live_data"
    
    # 核心 SQL：关联查询、模糊匹配、分组统计与数组聚合
    sql = """
        SELECT 
            COALESCE(u.user_name, g.user_name) AS user_name,
            g.gift_name,
            SUM(g.group_count * g.combo_count) AS total_count,
            u.sec_uid,
            array_agg(TO_CHAR(g.send_time, 'HH24:MI:SS') ORDER BY g.send_time) AS time_list,
            MIN(g.send_time) AS first_time
        FROM live_gifts g
        LEFT JOIN users u ON g.user_id = u.user_id
        WHERE g.room_id = '7612642193773251374'
          AND g.send_time >= '2026-03-02 20:59:00'
          AND g.send_time < '2026-03-02 21:50:00'
          AND g.gift_name LIKE '%宇宙之心%'
        GROUP BY u.user_name, g.user_name, g.gift_name, u.sec_uid
        ORDER BY first_time ASC;
    """
    
    print("🔌 正在连接数据库并执行查询...")
    try:
        pool = await asyncpg.create_pool(dsn=pg_dsn)
        async with pool.acquire() as conn:
            records = await conn.fetch(sql)
        await pool.close()
    except Exception as e:
        print(f"❌ 数据库查询失败: {e}")
        return

    # 构建带有极简美观 CSS 样式的 HTML 骨架
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>陈泽直播间 - “宇宙之心”</title>
        <style>
            body { font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; margin: 30px; background-color: #f4f7f6; color: #333; }
            h2 { text-align: center; color: #2c3e50; margin-bottom: 20px; }
            table { width: 100%; border-collapse: collapse; background-color: #fff; box-shadow: 0 2px 15px rgba(0,0,0,0.05); border-radius: 8px; overflow: hidden; }
            th, td { border: 1px solid #eaeaea; padding: 14px 20px; text-align: center; }
            th { background-color: #f8f9fa; color: #495057; font-weight: 600; text-transform: uppercase; font-size: 14px; }
            tr:nth-child(even) { background-color: #fcfcfc; }
            tr:hover { background-color: #f1f5f9; transition: background-color 0.2s; }
            a.profile-link { display: inline-block; padding: 6px 12px; background-color: #e2e8f0; color: #475569; border-radius: 4px; text-decoration: none; font-size: 13px; font-weight: 500; transition: all 0.2s; }
            a.profile-link:hover { background-color: #3b82f6; color: #fff; }
            .time-list { max-width: 350px; text-align: left; font-size: 13px; color: #64748b; line-height: 1.6; word-break: break-all; }
            .empty-data { text-align: center; padding: 50px; color: #94a3b8; }
        </style>
    </head>
    <body>
        <h2>陈泽直播间 (2026-03-02 20:59-21:50) “宇宙之心”</h2>
    """

    if not records:
        html_content += '<div class="empty-data">该时间段内未查询到符合条件的礼物数据。</div></body></html>'
    else:
        html_content += """
            <table>
                <tr>
                    <th width="5%">序号</th>
                    <th width="15%">用户名</th>
                    <th width="15%">礼物名</th>
                    <th width="10%">个数</th>
                    <th width="15%">主页链接</th>
                    <th width="40%">赠送时间</th>
                </tr>
        """
        
        # 遍历注入数据
        for idx, row in enumerate(records, 1):
            user_name = row['user_name'] or '神秘人'
            gift_name = row['gift_name']
            total_count = row['total_count']
            sec_uid = row['sec_uid']
            
            # 生成抖音主页外链
            if sec_uid:
                profile_link = f'<a class="profile-link" href="https://www.douyin.com/user/{sec_uid}" target="_blank">查看主页</a>'
            else:
                profile_link = '<span style="color:#cbd5e1; font-size: 13px;">暂无主页</span>'
                
            # 将 PostgreSQL 聚合出来的数组用分号拼接
            times_str = " ; ".join(row['time_list'])
            
            html_content += f"""
                <tr>
                    <td>{idx}</td>
                    <td style="font-weight: 500;">{user_name}</td>
                    <td style="color: #e11d48; font-weight: bold;">{gift_name}</td>
                    <td style="font-size: 18px; font-weight: bold;">{total_count}</td>
                    <td>{profile_link}</td>
                    <td class="time-list">{times_str}</td>
                </tr>
            """
            
        html_content += """
            </table>
        </body>
        </html>
        """
        
    # 落盘保存
    filename = "chenze_gifts_report.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"✅ 导出成功！共找到 {len(records)} 条合并后的高净值记录。")
    print(f"📄 报表已生成至当前目录下的: {filename}")

if __name__ == "__main__":
    asyncio.run(export_html())