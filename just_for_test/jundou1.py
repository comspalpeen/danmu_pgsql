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
        WHERE g.room_id = '7628266957075778340'
          AND g.send_time >= '2026-04-14 00:08:00 '
          AND g.send_time < '2026-04-14 01:22:59'
          AND (g.gift_name LIKE '%跑车%' OR g.gift_name LIKE '%钻石跑车%' OR g.gift_name LIKE '%跑车%' )
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

    # 构建带有极简美观 CSS 样式的 HTML 骨架 (针对竖屏和桌面端居中优化)
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>刘军-直播间 - “宝箱”</title>
        <style>
            body { 
                font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; 
                margin: 0; 
                padding: 20px 10px; 
                background-color: #e2e8f0; 
                color: #333; 
            }
            /* 核心容器：限制最大宽度，电脑端居中显示，形似手机屏幕 */
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
            /* 允许表格在极端窄屏下横向微调滚动，保证排版不乱 */
            .table-wrapper {
                width: 100%;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }
            table { 
                width: 100%; 
                border-collapse: collapse; 
                min-width: 450px; /* 保证一用户一行不被过度挤压 */
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
            <h2>刘军直播间 (00:08-01:23) “跑车”</h2>
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
        
        # 遍历注入数据
        for idx, row in enumerate(records, 1):
            user_name = row['user_name'] or '神秘人'
            gift_name = row['gift_name']
            total_count = row['total_count']
            sec_uid = row['sec_uid']
            
            # 生成抖音主页外链
            if sec_uid:
                profile_link = f'<a class="profile-link" href="https://www.iesdouyin.com/share/user/{sec_uid}" target="_blank">主页</a>'
            else:
                profile_link = '<span style="color:#cbd5e1; font-size: 12px;">暂无</span>'
                
            # 将 PostgreSQL 聚合出来的数组用换行或分号拼接，竖屏下用空格或更紧凑的符号
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
        
    print(f"✅ 导出成功！共找到 {len(records)} 条合并后的高净值记录。")
    print(f"📄 报表已生成至当前目录下的: {filename}")

if __name__ == "__main__":
    asyncio.run(export_html())