import asyncio
import asyncpg

async def export_html():
    pg_dsn = "postgresql://postgres:chufale@localhost:2077/dy_live_data"
    
    # 修改点：将 g.room_id = '...' 改为 g.room_id IN ('...', '...')
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
        WHERE g.room_id IN ('7613013280386321190', '7613038873341414190')
          AND g.send_time >= '2026-03-03 20:59:00'
          AND g.send_time < '2026-03-03 23:06:00'
          AND g.gift_name LIKE '%宇宙之心%'
        GROUP BY u.user_name, g.user_name, g.gift_name, u.sec_uid
        ORDER BY first_time ASC;
    """
    
    print("🔌 正在连接数据库并合并查询两个直播间数据...")
    try:
        pool = await asyncpg.create_pool(dsn=pg_dsn)
        async with pool.acquire() as conn:
            records = await conn.fetch(sql)
        await pool.close()
    except Exception as e:
        print(f"❌ 数据库查询失败: {e}")
        return

    # HTML 模板保持不变，标题可以微调
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>陈泽直播间 - 宇宙之心</title>
        <style>
            body { font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; margin: 0; padding: 20px 10px; background-color: #e2e8f0; color: #333; }
            .app-container { max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); padding: 15px; overflow: hidden; }
            h2 { text-align: center; color: #1e293b; font-size: 16px; margin-top: 5px; margin-bottom: 15px; }
            .table-wrapper { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
            table { width: 100%; border-collapse: collapse; min-width: 450px; }
            th, td { border-bottom: 1px solid #f1f5f9; padding: 10px 4px; text-align: center; font-size: 13px; }
            th { background-color: #f8fafc; color: #64748b; font-weight: 600; white-space: nowrap; }
            tr:last-child td { border-bottom: none; }
            .user-name { font-weight: 600; color: #0f172a; max-width: 80px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: inline-block; vertical-align: middle; }
            .gift-info { color: #e11d48; font-weight: bold; white-space: nowrap; }
            .gift-count { font-size: 16px; margin-left: 2px;}
            a.profile-link { display: inline-block; padding: 4px 8px; background-color: #f1f5f9; color: #475569; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 500; white-space: nowrap; }
            .time-list { text-align: left; font-size: 12px; color: #94a3b8; line-height: 1.4; max-width: 150px; }
            .empty-data { text-align: center; padding: 40px 0; color: #94a3b8; font-size: 14px; }
        </style>
    </head>
    <body>
        <div class="app-container">
            <h2>陈泽直播间3月3日“宇宙之心”汇总</h2>
    """

    if not records:
        html_content += '<div class="empty-data">该时间段内未查询到符合条件的礼物数据。</div></div></body></html>'
    else:
        html_content += """
            <div class="table-wrapper">
                <table>
                    <tr>
                        <th width="8%">#</th>
                        <th width="22%">用户</th>
                        <th width="25%">礼物</th>
                        <th width="15%">主页</th>
                        <th width="30%">时间</th>
                    </tr>
        """
        
        for idx, row in enumerate(records, 1):
            user_name = row['user_name'] or '神秘人'
            gift_name = row['gift_name']
            total_count = row['total_count']
            sec_uid = row['sec_uid']
            
            profile_link = f'<a class="profile-link" href="https://www.douyin.com/user/{sec_uid}" target="_blank">主页</a>' if sec_uid else '<span style="color:#cbd5e1; font-size: 12px;">暂无</span>'
            times_str = " ".join(row['time_list'])
            
            html_content += f"""
                    <tr>
                        <td style="color: #94a3b8;">{idx}</td>
                        <td><span class="user-name" title="{user_name}">{user_name}</span></td>
                        <td><span class="gift-info">{gift_name}<span class="gift-count">×{total_count}</span></span></td>
                        <td>{profile_link}</td>
                        <td class="time-list">{times_str}</td>
                    </tr>
            """
            
        html_content += "</table></div></div></body></html>"
        
    filename = "chenze_combined_report.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"✅ 导出成功！已合并两个直播间数据。")
    print(f"📄 报表已生成: {filename}")

if __name__ == "__main__":
    asyncio.run(export_html())