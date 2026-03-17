from fastapi import APIRouter, Query
import aiohttp
import re
import orjson as json
from backend_api.common.config import HEADERS
from backend_api.common.utils import get_ttwid

class DouyinAsyncSearcher:
    def __init__(self):
        self.headers = HEADERS.copy()

    async def get_profile(self, keyword: str):
        keyword = keyword.strip()
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            # 1. 处理短链
            if "v.douyin.com" in keyword:
                try:
                    async with session.get(keyword, allow_redirects=False, timeout=5) as resp:
                        if resp.status in [301, 302]:
                            keyword = resp.headers.get('Location', keyword)
                except: pass

            # 2. 提取/转换 sec_uid
            real_sec_uid = None
            pattern = r'(?:user/|sec_uid=)?(MS4wLjABAAAA[A-Za-z0-9_\\-]+)'
            match = re.search(pattern, keyword)
            if match:
                real_sec_uid = match.group(1)
            elif "http" not in keyword: 
                # 尝试用 unique_id (抖音号) 换 sec_uid
                conv_url = "https://www.iesdouyin.com/web/api/v2/user/info/"
                try:
                    async with session.get(conv_url, params={"unique_id": keyword}, timeout=5) as r:
                        res_json = await r.json()
                        if res_json.get("status_code") == 0:
                            real_sec_uid = res_json.get("user_info", {}).get("sec_uid")
                except: pass

            # 3. 核心请求 (直播间接口)
            api_url = "https://live.douyin.com/webcast/user/"
            params = {
                "aid": "6383",
                "device_platform": "web",
                "language": "zh-CN",
                "live_id": "1",
            }
            if real_sec_uid:
                params["sec_target_uid"] = real_sec_uid
            elif keyword.isdigit():
                params["target_uid"] = keyword
            else:
                return {"error": "无法解析有效 ID"}

            try:
                async with session.get(api_url, params=params, timeout=8) as resp:
                    data = await resp.json()
                    u = data.get("data")
                    if not u: return {"error": "未查询到数据 (可能参数失效)"}

                    # --- 数据解析 ---
                    nickname = u.get("nickname", "未知用户")
                    current_sec_uid = u.get("sec_uid") or real_sec_uid

                    # 🔥 真实身份照妖镜逻辑 (原有功能保留)
                    real_identity = None
                    if "神秘人" in nickname or u.get("mystery_man") == 1:
                        try:
                            ies_url = "https://www.iesdouyin.com/web/api/v2/user/info/"
                            async with session.get(ies_url, params={"sec_uid": current_sec_uid}, timeout=5) as r_ies:
                                ies_data = await r_ies.json()
                                if ies_data.get("status_code") == 0:
                                    ies_info = ies_data.get("user_info", {})
                                    real_name = ies_info.get("nickname")
                                    if real_name and real_name != nickname:
                                        real_identity = {
                                            "nickname": real_name,
                                            "avatar_url": ies_info.get("avatar_medium", {}).get("url_list", [""])[0]
                                        }
                        except: pass

                    # 认证信息
                    verify_label = "无"
                    auth_info = u.get("authentication_info") or {} 
                    cert_info_str = auth_info.get("account_cert_info")
                    if cert_info_str:
                        try:
                            cert_data = json.loads(cert_info_str)
                            verify_label = cert_data.get("label_text", "")
                        except: pass
                    if not verify_label or verify_label == "无":
                        verify_label = u.get("custom_verify") or u.get("enterprise_verify_reason") or "无"

                    # 财富等级
                    pay_grade = u.get("pay_grade") or {}
                    min_d = pay_grade.get("this_grade_min_diamond", 0)
                    max_d = pay_grade.get("this_grade_max_diamond", 0)
                    
                    grade_icons = (pay_grade.get("new_im_icon_with_level") or {}).get("url_list", [])
                    if not grade_icons:
                        grade_icons = (pay_grade.get("new_live_icon") or {}).get("url_list", [])
                    
                    avatars = (u.get("avatar_large") or {}).get("url_list", [])
                    follow_info = u.get("follow_info") or {}

                    return {
                        "nickname": nickname,
                        "display_id": u.get("display_id", "未知"), # 抖音号
                        "uid": str(u.get("id_str") or u.get("id", "")),
                        "sec_uid": current_sec_uid,
                        "avatar_url": avatars[0] if avatars else "",
                        "grade_icon_url": grade_icons[0] if grade_icons else "",
                        "verify": verify_label,
                        "gender": {1: "男", 2: "女"}.get(u.get("gender"), "未知"),
                        "city": u.get("city") or "未知",
                        "follower_count": follow_info.get("follower_count", 0),
                        "following_count": follow_info.get("following_count", 0),
                        "pay_level": pay_grade.get("level", 0),
                        "min_diamond": min_d,
                        "max_diamond": max_d,
                        "signature": u.get("signature", ""),
                        "secret": "私密" if u.get("secret") == 1 else "正常",
                        "real_identity": real_identity 
                    }
            except Exception as e:
                return {"error": f"请求异常: {str(e)}"}

    async def get_room_relation(self, user_sec_uid: str, streamer_input: str):
        streamer_input = streamer_input.strip()
        ttwid = await get_ttwid()

        req_headers = self.headers.copy()
        if ttwid:
            req_headers["Cookie"] = f"ttwid={ttwid};"

        async with aiohttp.ClientSession(headers=req_headers) as session:
            # 1. 解析主播 ID
            anchor_id = None
            sec_anchor_id = None
            
            pattern = r'(?:user/|sec_uid=)?(MS4wLjABAAAA[A-Za-z0-9_\\-]+)'
            match = re.search(pattern, streamer_input)
            if match:
                sec_anchor_id = match.group(1)
            elif "http" in streamer_input or "v.douyin.com" in streamer_input:
                try:
                    async with session.get(streamer_input, allow_redirects=False) as resp:
                        if resp.status in [301, 302]:
                            loc = resp.headers.get('Location', '')
                            match_sec = re.search(pattern, loc)
                            if match_sec: sec_anchor_id = match_sec.group(1)
                except: pass
            else:
                # 尝试用 unique_id 换 sec_uid
                is_converted = False
                try:
                    conv_url = "https://www.iesdouyin.com/web/api/v2/user/info/"
                    async with session.get(conv_url, params={"unique_id": streamer_input}, timeout=3) as r:
                        res = await r.json()
                        if res.get("status_code") == 0:
                            sec_anchor_id = res.get("user_info", {}).get("sec_uid")
                            is_converted = True
                except: pass
                
                if not is_converted and streamer_input.isdigit():
                    anchor_id = streamer_input

            if not anchor_id and not sec_anchor_id:
                return {"error": "无法解析主播信息"}

            # 2. 获取主播基本信息 (为了拿 display_id 和 grade_icon)
            anchor_info = {}
            query_key = sec_anchor_id if sec_anchor_id else anchor_id
            
            # 复用 get_profile
            anchor_profile = await self.get_profile(query_key)
            
            if not anchor_profile.get("error"):
                anchor_info = {
                    "nickname": anchor_profile.get("nickname"),
                    "avatar_url": anchor_profile.get("avatar_url"),
                    "display_id": anchor_profile.get("display_id"),      # 🔥 必须透传
                    "grade_icon_url": anchor_profile.get("grade_icon_url"), # 🔥 必须透传
                    "sec_uid": anchor_profile.get("sec_uid"),
                    "follower_count": anchor_profile.get("follower_count", 0)
                }
                if anchor_profile.get("sec_uid"):
                    sec_anchor_id = anchor_profile.get("sec_uid")
            max_retries = 2 # 最多尝试 2 次 (第一次失败，刷新 ttwid 后重试第二次)
        
            for attempt in range(max_retries):
                # 如果是第 2 次尝试 (attempt > 0)，强制刷新 ttwid
                use_fresh_token = (attempt > 0)
                ttwid = await get_ttwid(force_refresh=use_fresh_token)
    
                req_headers = self.headers.copy()
                if ttwid:
                    req_headers["Cookie"] = f"ttwid={ttwid};"
            # 3. 请求关系接口
            api_url = "https://live.douyin.com/webcast/user/profile/"
            params = {
                "aid": "6383", "app_name": "douyin_web", "live_id": "1",
                "device_platform": "web", "language": "zh-CN",
                "sec_target_uid": user_sec_uid,
                "anchor_id": anchor_id if anchor_id else "",
                "sec_anchor_id": sec_anchor_id if sec_anchor_id else "",
                "current_room_id":"43964399996"
            }
            
            try:
                async with session.get(api_url, params=params, timeout=8) as resp:
                    data = await resp.json()
                    user_profile = data.get("data", {}).get("user_profile", {})
                    
                    if not user_profile:
                        return {"error": "未获取到关系数据", "anchor_info": anchor_info}

                    # 解析
                    fans_club = user_profile.get("fans_club", {}).get("data", {})
                    fans_level = fans_club.get("level", 0)
                    
                    icons = fans_club.get("badge", {}).get("icons", {})
                    badge_url = ""
                    if icons:
                        target_icon = icons.get("4") or icons.get("1") or list(icons.values())[0]
                        if target_icon:
                            badge_url = target_icon.get("url_list", [""])[0]

                    is_member = user_profile.get("subscribe_info", {}).get("is_member", False)
                    is_admin = user_profile.get("admin_info", {}).get("is_admin", False)
                    
                    return {
                        "anchor_info": anchor_info,
                        "fans_level": fans_level,
                        "fans_badge_url": badge_url,
                        "is_member": is_member,
                        "is_admin": is_admin 
                    }

            except Exception as e:
                return {"error": f"请求失败: {str(e)}", "anchor_info": anchor_info}

searcher = DouyinAsyncSearcher()
router = APIRouter(prefix="/api/check", tags=["check"])

@router.get("/user")
async def check_user_profile(q: str = Query(...)):
    return await searcher.get_profile(q)

@router.get("/relation")
async def check_room_relation(user_sec: str = Query(...), streamer: str = Query(...)):
    return await searcher.get_room_relation(user_sec, streamer)