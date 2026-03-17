import re
import os
import aiohttp
from backend_api.common.database import get_redis
from backend_api.common.user_agents import get_dynamic_headers
from backend_api.common.config import HEADERS

async def get_ttwid(force_refresh=False) -> str:
    redis = await get_redis()
    cache_key = "douyin:ttwid"
    
    # 如果不是强制刷新，先查 Redis
    if not force_refresh:
        try:
            cached_ttwid = await redis.get(cache_key)
            if cached_ttwid:
                return cached_ttwid
        except Exception as e:
            print(f"[Redis Error] get ttwid: {e}")

    # 强制刷新或缓存不存在：去首页取
    print("🔄 [Searcher] 正在获取新的 ttwid...")
    ttwid = ""
    headers = HEADERS.copy()
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get("https://live.douyin.com/", timeout=5) as resp:
                cookies = session.cookie_jar.filter_cookies("https://live.douyin.com/")
                ttwid = cookies.get("ttwid", {}).value if "ttwid" in cookies else ""
    except Exception as e:
        print(f"[Network Error] fetch ttwid: {e}")

    if ttwid and redis:
        try:
            await redis.setex(cache_key, 3600, ttwid)
        except: pass
    
    return ttwid

def build_avatar_url(filename: str) -> str:
    if not filename: return ""
    if filename.startswith("http"): return filename

    # 1. 核心步骤：去掉后缀，拿到纯 ID 部分
    # 无论输入是 "abc.png" 还是 "abc"，name_part 都会是 "abc"
    name_part = os.path.splitext(filename)[0].lower()
    
    # 2. 判断纯 ID 部分是否符合 32 位 MD5 哈希特征
    is_hash = bool(re.fullmatch(r'[a-f0-9]{32}', name_part))

    # 3. 如果是哈希，强制走 webcast 专用路径
    if is_hash:
        # 注意：webcast 路径通常固定使用 .png 且带 tplv 参数
        return f"https://p3-webcast.douyinpic.com/img/webcast/{name_part}.png~tplv-obj.image"

    # 4. 如果是带有 "mystery" 字样的通用神秘人
    if "mystery" in name_part:
        return "https://p3-webcast.douyinpic.com/img/webcast/mystery_man_thumb_avatar.png~tplv-obj.image"

    # 5. 常规用户头像（比如 user_123.jpg）
    # 如果数据库里没后缀，补上 .jpeg；有后缀就用原有的
    final_filename = filename if "." in filename else f"{filename}.jpeg"
    return f"https://p11.douyinpic.com/aweme/100x100/aweme-avatar/{final_filename}?from=3067671334"



def build_grade_icon(filename: str) -> str:
    """拼接财富等级图标完整 URL"""
    if not filename: return ""
    if filename.startswith("http"): return filename
    return f"https://p3-webcast.douyinpic.com/img/webcast/{filename}~tplv-obj.image"

def build_fans_icon(filename: str) -> str:
    """拼接粉丝团等级图标完整 URL"""
    if not filename: return ""
    if filename.startswith("http"): return filename
    return f"https://p3-webcast.douyinpic.com/img/webcast/{filename}~tplv-obj.image"

def build_gift_icon(filename: str) -> str:
    """拼接礼物图标完整 URL"""
    if not filename: return ""
    if filename.startswith("http"): return filename
    return f"https://p3-webcast.douyinpic.com/img/webcast/{filename}~tplv-obj.png"