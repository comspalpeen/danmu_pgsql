import asyncio
import asyncpg
import random
import datetime

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
          AND g.send_time >= '2026-03-02 22:30:00'
          AND g.send_time < '2026-03-02 22:41:00'
          AND (g.gift_name LIKE '%抖音1号%' OR g.gift_name LIKE '%火箭%' OR g.gift_name LIKE '%为爱启航%' )
        GROUP BY u.user_name, g.user_name, g.gift_name, u.sec_uid
        ORDER BY first_time ASC;
    """
    
    print("🔌 正在连接数据库并执行查询...")
    
    # 用来存放最终所有数据的列表
    all_records = []
    
    try:
        pool = await asyncpg.create_pool(dsn=pg_dsn)
        async with pool.acquire() as conn:
            records = await conn.fetch(sql)
            # 将 asyncpg.Record 转换为普通字典以便后续追加和修改
            all_records = [dict(record) for record in records]
        await pool.close()
    except Exception as e:
        print(f"❌ 数据库查询失败: {e}，将仅生成内置数据。")

    # ==========================
    # 开始注入指定用户数据
    # ==========================
    mock_users = [
        ("吃冻梨硌了牙", "MS4wLjABAAAAuesUkrs9YMVxzqLE07PT9OtsVtW9m2-Scz7Uow5-gCw"),
        ("Aila（三角洲行动）", "MS4wLjABAAAAyLI8mvk13Wt_Tl_g7TJgDHIjh5WV_5EoTCamTDtccUvxGZpdycieZ6D5NCFXP39t"),
        ("皮皮-", "MS4wLjABAAAAbhM5hgbB-WlckZ2NzzgqqymgecD5eRGC9G-Xkm4uAIw"),
        ("ovo", "MS4wLjABAAAAAmIqsNzN9mcAbHnmpjxvp8YJ1qW97lWWM3wuVJ0nTXM"),
        ("ee.", "MS4wLjABAAAA5tCGLwu1Wid18Dwn9mNpVmFhz-NxyFAuctzijcO9AHc"),
        ("iiis.", "MS4wLjABAAAAbRfvEX5czvumlR8R_la5RxfCcLGeVGOq7ICYeyBWqtgeU-lO9pD-PnXsANDBhmaU"),
        ("iduce1.77", "MS4wLjABAAAAdJVygNqTC38MWeWomWxtJn-9U_Xjw_6kmEo2w-2FyaI"),
        ("👾 Conan", "MS4wLjABAAAAydM7aKzxwwS6k-BqE7g2K7WtjR_88Km3RYMn_HkoD8MrFeAyebGfKOBf4M5YrssQ")
    ]

    # 定义随机时间范围：22:30:00 到 22:40:59
    start_time = datetime.datetime(2026, 3, 2, 22, 30, 0)
    end_time = datetime.datetime(2026, 3, 2, 22, 40, 59)
    time_diff_seconds = int((end_time - start_time).total_seconds())

    for name, sec_uid in mock_users:
        # 随机生成一个时间差
        random_seconds = random.randint(0, time_diff_seconds)
        mock_time = start_time + datetime.timedelta(seconds=random_seconds)
        time_str = mock_time.strftime('%H:%M:%S')
        
        # 组装与数据库查询结果结构一致的字典
        all_records.append({
            'user_name': name,
            'gift_name': '抖音1号',
            'total_count': 1,
            'sec_uid': sec_uid,
            'time_list': [time_str],
            'first_time': mock_time
        })

    # 合并后按照首次送礼时间重新排序，确保穿插在真实数据中毫不违和
    all_records.sort(key=lambda x: x['first_time'])
    # ==========================

    # 构建带有极简美观 CSS 样式的 HTML 骨架
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>陈泽直播间 - “抖音1号”</title>
        <style>
            body { 
                font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; 
                margin: 0; 
                padding: 20px 10px; 
                background-color: #e2e8f0; 
                color: #333; 
            }
            .app-container { 
                max-width: 600px; 
                margin: 0 auto; 
                background: #fff; 
                border-radius: 12px; 
                box-shadow: 0 4px 20px rgba(0,0,0,0.08); 
                padding: 15px; 
                overflow: hidden;
            }
            h2 { 
                text-align: center; 
                color: #1e293b; 
                font-size: 16px; 
                margin-top: 5px;
                margin-bottom: 15px; 
            }
            .table-wrapper {
                width: 100%;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }
            table { 
                width: 100%; 
                border-collapse: collapse; 
                min-width: 450px; 
            }
            th, td { 
                border-bottom: 1px solid #f1f5f9; 
                padding: 10px 4px; 
                text-align: center; 
                font-size: 13px; 
            }
            th { 
                background-color: #f8fafc; 
                color: #64748b; 
                font-weight: 600; 
                white-space: nowrap; 
            }
            tr:last-child td { border-bottom: none; }
            .user-name { 
                font-weight: 600; 
                color: #0f172a; 
                max-width: 80px; 
                white-space: nowrap; 
                overflow: hidden; 
                text-overflow: ellipsis; 
                display: inline-block;
                vertical-align: middle;
            }
            .gift-info { color: #e11d48; font-weight: bold; white-space: nowrap; }
            .gift-count { font-size: 16px; margin-left: 2px;}
            a.profile-link { 
                display: inline-block; 
                padding: 4px 8px; 
                background-color: #f1f5f9; 
                color: #475569; 
                border-radius: 6px; 
                text-decoration: none; 
                font-size: 12px; 
                font-weight: 500; 
                white-space: nowrap;
            }
            .time-list { 
                text-align: left; 
                font-size: 12px; 
                color: #94a3b8; 
                line-height: 1.4; 
                max-width: 150px;
            }
            .empty-data { text-align: center; padding: 40px 0; color: #94a3b8; font-size: 14px; }
        </style>
    </head>
    <body>
        <div class="app-container">
            <h2>陈泽直播间 (22:30-22:41) “抖音1号”</h2>
    """

    if not all_records:
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
        
        # 遍历注入数据
        for idx, row in enumerate(all_records, 1):
            user_name = row['user_name'] or '神秘人'
            gift_name = row['gift_name']
            total_count = row['total_count']
            sec_uid = row['sec_uid']
            
            # 生成抖音主页外链
            if sec_uid:
                profile_link = f'<a class="profile-link" href="https://www.douyin.com/user/{sec_uid}" target="_blank">主页</a>'
            else:
                profile_link = '<span style="color:#cbd5e1; font-size: 12px;">暂无</span>'
                
            times_str = " ".join(row['time_list'])
            
            html_content += f"""
                    <tr>
                        <td style="color: #94a3b8;">{idx}</td>
                        <td><span class="user-name" title="{user_name}">{user_name}</span></td>
                        <td>
                            <span class="gift-info">{gift_name}<span class="gift-count">×{total_count}</span></span>
                        </td>
                        <td>{profile_link}</td>
                        <td class="time-list">{times_str}</td>
                    </tr>
            """
            
        html_content += """
                </table>
            </div>
        </div>
    </body>
    </html>
    """
        
    # 落盘保存
    filename = "chenze_gifts_1号_mobile.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"✅ 导出成功！共生成 {len(all_records)} 条记录（包含合成数据）。")
    print(f"📄 报表已生成至当前目录下的: {filename}")

if __name__ == "__main__":
    asyncio.run(export_html())