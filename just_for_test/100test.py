import asyncio
import aiohttp
import asyncpg
import json

# ================= 配置区 =================
ROOM_ID = "7612240511935515442"
# 把你浏览器里的完整 Cookie 填到这里
COOKIE = "live_use_vvc=%22false%22; SelfTabRedDotControl=%5B%5D; bd_ticket_guard_client_web_domain=2; enter_pc_once=1; UIFID_TEMP=d4579b5b1721ffdd22d8a6ff378781159e3b4e5a1248a83fc8c708ec2606b70529d64af07fcaf4d876ead2b66751c79fc89cd1cce7bcc45e94711957ccada980de8d21ae6c3304ac775ef3ffcbf135d122222778758f554cdc9fdf8ad54e9b6d772ee49c505f70aab1abf0933e55f010; UIFID=d4579b5b1721ffdd22d8a6ff378781159e3b4e5a1248a83fc8c708ec2606b70529d64af07fcaf4d876ead2b66751c79fc89cd1cce7bcc45e94711957ccada980af7855a857189ec2af825e6efe063405abfe214c20f6ba674e1d86e5b793a70990f4cd271cc14c7f6ac4836268d842b63c71c1cd154b0532d977b1b479f76b14f552d6333646d34e59de5e9dfad68058d2f3839748f2a2913327932d916e3fd0e7a8241120cd54857ff8a1744a4278016812ce3a0055d19fbed347adc34f1f08; xgplayer_device_id=13603423669; xgplayer_user_id=652422818007; my_rd=2; fpk1=U2FsdGVkX19PfrcYVnGgljEyOvcARAho+4pWj1x55NHfsC/cZPV7KQwMvQah/U7eWtwFl9gBDgggGhziUmNHgQ==; fpk2=d2ad6785d256851dd366703bdc61aa61; SEARCH_RESULT_LIST_TYPE=%22single%22; n_mh=-OhWsbwzm7XFi92mLW4UILrJL5ZYyWH55ubBZ2GrwfA; __ac_signature=_02B4Z6wo00f014AN4GAAAIDA35jrrW6cILOALeTAAIjff4; is_staff_user=false; d_ticket=7c143bbb1a6abebc8ec8dfc7fa80ce6b6bd5a; _bd_ticket_crypt_doamin=2; __security_server_data_status=1; enter_pc_first_on_day=20251209; s_v_web_id=verify_mjfi6bdp_eZYJEXV6_Buae_4wOM_8iid_24UDGFIEUYBr; passport_csrf_token=15b89b00808450abf96e6fd9621ed558; passport_csrf_token_default=15b89b00808450abf96e6fd9621ed558; is_dash_user=1; passport_mfa_token=CjewkEITooXeRxn%2Ffaf8yKS4CCxj9Ij82sozva6tBOCg9QY0R3FI86x1uULmq2swrJbKShC02a2gGkoKPAAAAAAAAAAAAABP%2FrmFBBvWo3CAMoC16LRzQD6k%2F5oDyu4E2kzsl9H7Z8ADxTC%2FYJcSPCIB20sraERU9xD%2F7YcOGPax0WwgAiIBA0XxjZg%3D; SEARCH_UN_LOGIN_PV_CURR_DAY=%7B%22date%22%3A1769438558488%2C%22count%22%3A1%7D; passport_assist_user=CkETc6ls3KoNuJ9NzMTBrpdufctEkpL4sKVg1h9oj4rBTwDRLz1LhujG29WWJlqmRzl3ivg-yZDFNSbrjAe52_M3OxpKCjwAAAAAAAAAAAAAT_9ztETAb1w8SayuEnCP_p8Hb9SZAIesGyQEoAsk1vlwX1ItmcURwqXAWpk15rqJ8hAQvPmHDhiJr9ZUIAEiAQNk2QGc; sid_guard=2523fe5a8b7d41230da52a161e8645d5%7C1769438741%7C5184000%7CFri%2C+27-Mar-2026+14%3A45%3A41+GMT; uid_tt=62295467de766a392e00f0ebf2908597; uid_tt_ss=62295467de766a392e00f0ebf2908597; sid_tt=2523fe5a8b7d41230da52a161e8645d5; sessionid=2523fe5a8b7d41230da52a161e8645d5; sessionid_ss=2523fe5a8b7d41230da52a161e8645d5; session_tlb_tag=sttt%7C8%7CJSP-Wot9QSMNpSoWHoZF1f_________AQ39ujnclViUTpMxKj26GD7CEKQoVKKmugWAXIMPrgQw%3D; sid_ucp_v1=1.0.0-KGU2ZDFlNzE0MjQwN2FiYWRhNGY5ZWQ2MmUyNmJiZDU4MDcyMWJhOTYKIQiYnOCOuPWlBxCV_N3LBhjvMSAMMLm94PUFOAVA-wdIBBoCbGYiIDI1MjNmZTVhOGI3ZDQxMjMwZGE1MmExNjFlODY0NWQ1; ssid_ucp_v1=1.0.0-KGU2ZDFlNzE0MjQwN2FiYWRhNGY5ZWQ2MmUyNmJiZDU4MDcyMWJhOTYKIQiYnOCOuPWlBxCV_N3LBhjvMSAMMLm94PUFOAVA-wdIBBoCbGYiIDI1MjNmZTVhOGI3ZDQxMjMwZGE1MmExNjFlODY0NWQ1; login_time=1769438741961; _bd_ticket_crypt_cookie=8216b71ef858e3b6bf58b8e992c9791c; __live_version__=%221.1.4.8263%22; __security_mc_1_s_sdk_cert_key=f26d509c-4527-a1f5; __security_mc_1_s_sdk_sign_data_key_web_protect=35200007-46f6-8d61; volume_info=%7B%22isUserMute%22%3Atrue%2C%22isMute%22%3Atrue%2C%22volume%22%3A0.51%7D; __security_mc_1_s_sdk_crypt_sdk=97c0be5f-4256-8608; download_guide=%223%2F20260207%2F0%22; strategyABtestKey=%221770567015.779%22; publish_badge_show_info=%220%2C0%2C0%2C1770567325060%22; playRecommendGuideTagCount=8; totalRecommendGuideTagCount=8; ttwid=1%7C8kCzoJAeW10gO7z3PS3bbNgrTzOe2JQOzNF19x1LOTE%7C1770575084%7C7bdaea1d43aaa39498866a24fbd4569f700cb1042a17cd930c134911668ff196; stream_player_status_params=%22%7B%5C%22is_auto_play%5C%22%3A0%2C%5C%22is_full_screen%5C%22%3A0%2C%5C%22is_full_webscreen%5C%22%3A0%2C%5C%22is_mute%5C%22%3A1%2C%5C%22is_speed%5C%22%3A1%2C%5C%22is_visible%5C%22%3A0%7D%22; _tea_utm_cache_3483=undefined; home_can_add_dy_2_desktop=%220%22; stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1920%2C%5C%22screen_height%5C%22%3A1080%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A16%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A0%7D%22; FOLLOW_NUMBER_YELLOW_POINT_INFO=%22MS4wLjABAAAAUE-AawRjwST5lBI2BjT1_b6ntgHPLWVyCldVL9n58arDLHGRMfWpbVscv75JBKfN%2F1770652800000%2F0%2F0%2F1770645888145%22; FOLLOW_LIVE_POINT_INFO=%22MS4wLjABAAAAUE-AawRjwST5lBI2BjT1_b6ntgHPLWVyCldVL9n58arDLHGRMfWpbVscv75JBKfN%2F1770652800000%2F0%2F0%2F1770645426844%22; gulu_source_res=eyJwX2luIjoiZDk4YTY2N2IxZTM2YjNjODRhZmU3NmYwODBmNzZkNzNjMWE2ODljMDQxNmNmMzg1MDk3ZDZhYTRkZjYwY2YyNyJ9; sdk_source_info=7e276470716a68645a606960273f276364697660272927676c715a6d6069756077273f276364697660272927666d776a68605a607d71606b766c6a6b5a7666776c7571273f275e58272927666a6b766a69605a696c6061273f27636469766027292762696a6764695a7364776c6467696076273f275e582729277672715a646971273f2763646976602729277f6b5a666475273f2763646976602729276d6a6e5a6b6a716c273f2763646976602729276c6b6f5a7f6367273f27636469766027292771273f2730343132343730313335323234272927676c715a75776a716a666a69273f2763646976602778; bit_env=Ttmme0WwMZnmFcg0TzDUbEtPIdrHPT5MLc70KolwPhG0YP4lvvP5Jls1WSpoyO1HPvr3M4n-HQxwYMlgDnwhzzCZzR5zSsDH6IrMhEpAVO0JDMqD3qc_UD4Qq2rraXB9-c0PyxSK-EtucqN-apta_3UGEZhGurCZnjrtJsWv30CKdgiHCmfYhNfTzanA23U8KZkul-2QD91rnTPQBmyveMGxFJzGZsoVkIWjihDVZDichZBn4d2zecMFgkTvQtkkgZS0q6v8enj7SbHi5UhjLB9uStAOH4fFtS_GsSS0FVkKEbyjc22MMguyFVQ1rE6Xjx8zqPKVqfwZUiFS5g2YH9fkIr06d-YVCKZhnu-K6q-NXwrEzz_7OGmsU1fq5-n-7a59yEVglMF0922IxzjrZ0-3Vn2fx8-3DNYIvr1VTi-45dlbYCl0vx1vGWUrTYE7HSYaF2b17CbvPRgOuRWnx9kiDwmpjzk4fkl5G6G7DwPSF3svXXvHfY4Y0wd3nMyC6nRS1xebL0KM_XaCZoMS7sCwqK2ZAPykq1WZFnC5BhM%3D; passport_auth_mix_state=yqxs3grc1nnh1jzbar3eh10k3vrhvdjs; odin_tt=97f5a8a0cf6cf7bad690b1e3fbee0dce297ca6f36d88ce1b55f7fd4c43e6675a57f354c510a96646e5f7af22fb4f982a8d6ff5d7d47875f931775a3a568e8cd7; xg_device_score=7.873851705001503; has_avx2=null; device_web_cpu_core=16; device_web_memory_size=8; csrf_session_id=c8612cddaedbd8233200aa892bac32af; bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCSU1HK3o2bm9FM1FoNUdOVm13S013dGYrSUpuWGZUOW1Nd2xySDBZN0JnUjhNNmROTThWUDlNL2xONjh1SEFOMkVLRmhtT04wQmtqQzNEVHFWRUY3elk9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D; live_can_add_dy_2_desktop=%221%22; IsDouyinActive=true; biz_trace_id=483adf80; bd_ticket_guard_client_data_v2=eyJyZWVfcHVibGljX2tleSI6IkJJTUcrejZub0UzUWg1R05WbXdLTXd0ZitJSm5YZlQ5bU13bHJIMFk3QmdSOE02ZE5NOFZQOU0vbE42OHVIQU4yRUtGaG1PTjBCa2pDM0RUcVZFRjd6WT0iLCJ0c19zaWduIjoidHMuMi42OWMzZWE5NDM3MmY5ZTY4Y2Y5ZTNiOTgyYzk3OTgwNjgyMmJhZjcyMjUxODRmOGVjNTY5YzI2YTVhNGE1ZTIxYzRmYmU4N2QyMzE5Y2YwNTMxODYyNGNlZGExNDkxMWNhNDA2ZGVkYmViZWRkYjJlMzBmY2U4ZDRmYTAyNTc1ZCIsInJlcV9jb250ZW50Ijoic2VjX3RzIiwicmVxX3NpZ24iOiJ2dzNtWStGZlFCNFlRYThaRlUxS3BXbzRsSC8xS1dBYXFSc0ZLeVRCM2Q4PSIsInNlY190cyI6IiNMTkIzSGIyYmdsM3JveitCMklEQ0hpS3pxcm9tZG93MDhBQXpNVjFrNzI5RXRpRTFzTmdBcXNrQWVYNkwifQ%3D%3D" 

# 你的完整 URL (去掉了多余部分，保留关键参数)
API_URL = f"https://live.douyin.com/webcast/ranklist/paygrade_seats/?aid=6383&app_name=douyin_web&live_id=1&device_platform=web&room_id={ROOM_ID}&seats_type=2"

# 数据库配置 (使用你 db.py 里的 DSN)
DB_DSN = "postgresql://postgres:chufale@127.0.0.1:2077/dy_live_data"
# ==========================================

async def fetch_paygrade_seats():
    """获取 API 千分榜名单"""
    headers = {
        "Cookie": COOKIE,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        print("⏳ 正在请求千分榜 API...")
        async with session.get(API_URL, headers=headers) as response:
            if response.status != 200:
                print(f"❌ API 请求失败，状态码: {response.status}")
                return []
            
            data = await response.json()
            seats = data.get("data", {}).get("stalls", [])[0].get("seats", [])
            
            api_users = {}
            for seat in seats:
                user_info = seat.get("user_info", {})
                uid = user_info.get("user_id")
                nickname = user_info.get("nick_name")
                if uid:
                    api_users[uid] = nickname
            
            print(f"✅ API 请求成功，共抓取到 {len(api_users)} 位千分榜用户。")
            return api_users

async def fetch_db_ws_users():
    """从数据库汇总 WS 抓到的礼物数据"""
    print("⏳ 正在查询本地数据库 WS 记录...")
    conn = await asyncpg.connect(DB_DSN)
    try:
        # 统计该房间内，每个用户的累计送礼钻石数
        sql = """
            SELECT user_id, user_name, SUM(total_diamond_count) as total_diamonds 
            FROM live_gifts 
            WHERE room_id = $1 
            GROUP BY user_id, user_name
        """
        records = await conn.fetch(sql, ROOM_ID)
        
        db_users = {}
        for r in records:
            db_users[r['user_id']] = {
                'nickname': r['user_name'],
                'total_diamonds': r['total_diamonds']
            }
        
        print(f"✅ 数据库查询成功，共找到 {len(db_users)} 位有送礼记录的用户。")
        return db_users
    finally:
        await conn.close()

async def main():
    api_users = await fetch_paygrade_seats()
    if not api_users:
        return
        
    db_users = await fetch_db_ws_users()
    
    print("\n" + "="*50)
    print(" 🔍 开始交叉比对 (阈值: 900钻)")
    print("="*50)
    
    mismatch_count = 0
    matched_count = 0
    
    for uid, nickname in api_users.items():
        ws_record = db_users.get(uid)
        
        if not ws_record:
            # 彻底被 WS 丢包，毫无记录
            print(f"⚠️ [幽灵漏单] {nickname} (UID: {uid}) -> 榜上有名，但 WS 数据库中【毫无记录】！")
            mismatch_count += 1
        else:
            total_diamonds = ws_record['total_diamonds']
            if total_diamonds < 900:
                # 抓到了，但金额不够 (小礼物被吞或部分丢包)
                print(f"⚠️ [金额不足] {nickname} (UID: {uid}) -> 榜上有名，但 WS 数据库中累计仅有: {total_diamonds} 钻")
                mismatch_count += 1
            else:
                # 完美匹配
                matched_count += 1
                
    print("\n" + "="*50)
    print(" 📊 测试总结报告")
    print("="*50)
    print(f"总计千分榜人数 : {len(api_users)}")
    print(f"完美匹配人数 (>=900钻): {matched_count}")
    print(f"未匹配人数 (<900钻/无记录) : {mismatch_count}")
    print(f"真实 WS 丢包率推算 : {mismatch_count / len(api_users) * 100:.2f}%" if api_users else "N/A")

if __name__ == "__main__":
    asyncio.run(main())