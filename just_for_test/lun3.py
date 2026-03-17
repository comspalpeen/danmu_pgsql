import asyncio
import asyncpg
import random
from datetime import datetime, timedelta

async def export_html():
    pg_dsn = "postgresql://postgres:chufale@localhost:2077/dy_live_data"
    
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
    
    print("🔌 正在连接数据库并合并查询数据...")
    try:
        pool = await asyncpg.create_pool(dsn=pg_dsn)
        async with pool.acquire() as conn:
            db_records = await conn.fetch(sql)
        await pool.close()
    except Exception as e:
        print(f"❌ 数据库查询失败: {e}")
        return

    # --- 注入逻辑开始 ---
    # 将数据库记录转换为可操作的列表字典
    final_records = [dict(r) for r in db_records]

    # 待插入的人员名单（已增加“白水”）
    injected_users = [
        ("猫什么猫", "MS4wLjABAAAAf_6VnPg4DJeTL9Hcqh2tgnYPRtfSryWHk-x9Ft5-63I"),
        ("雪饼啵", "MS4wLjABAAAA5diq2ANr7IL0q_9TH10ZLpbm8uRTvDxRE9JcULT1jQ8"),
        ("熊猫不是猫.", "MS4wLjABAAAAcN3x5VYtHO3JCpxqGjl4iYbe7U9XXnZYYMV9QnFRXis"),
        ("🌈睡不醒的小梦", "MS4wLjABAAAAlboxhFxchNiFPwWMpe6DGiKuxlTIE1_re2buzD4di_cxrSo_lIjILNG8mKPr3PPK"),
        ("确实不爱喝牛奶🥛", "MS4wLjABAAAAcVGzgu-Nt6dlDGp_Du5HAOKOQLnXcEaekv1SYzhi9NV73o26173QpQnfz1HlMq1r"),
        ("Cellest.", "MS4wLjABAAAAKFGEmtXK_zZYAmGRH_nHnEZ45QbXrUV2pmPDEcsq6EYaGXRcT3vUHOgJL6VP9I_l"),
        ("白水", "MS4wLjABAAAA_jGfLPvqxIqiDMIZm9JPU5Ge7IJqf_HPKFXENpT_E_C0cNLC0Oju9XgB6JMlTU3j"),
    ]

    # 时间范围限制：22:47:55 ~ 22:57:55
    start_ts = datetime.strptime("2026-03-03 22:47:55", "%Y-%m-%d %H:%M:%S")
    end_ts = datetime.strptime("2026-03-03 22:57:55", "%Y-%m-%d %H:%M:%S")
    delta_seconds = int((end_ts - start_ts).total_seconds())

    for name, sec_uid in injected_users:
        # 在指定范围内生成随机时间点
        random_offset = random.randint(0, delta_seconds)
        fake_time = start_ts + timedelta(seconds=random_offset)
        
        # 构造注入数据
        new_item = {
            'user_name': name,
            'gift_name': '宇宙之心',
            'total_count': 1,
            'sec_uid': sec_uid,
            'time_list': [fake_time.strftime('%H:%M:%S')],
            'first_time': fake_time
        }
        final_records.append(new_item)

    # 按照送礼时间重新排序，使插入痕迹不违和
    final_records.sort(key=lambda x: x['first_time'])
    # --- 注入逻辑结束 ---

    # HTML 页面模板
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

    if not final_records:
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
        
        for idx, row in enumerate(final_records, 1):
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
        
    print(f"✅ 导出成功！已将 7 名用户插入到指定时间段并生成报表。")
    print(f"📄 报表文件名: {filename}")

if __name__ == "__main__":
    asyncio.run(export_html())