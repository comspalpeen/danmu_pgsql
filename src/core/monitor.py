# monitor.py
import orjson as json
import random
import re
import logging
import asyncio
import aiohttp
from typing import List, Dict, Optional
from datetime import datetime
from src.db.db import AsyncPostgresHandler

logger = logging.getLogger("Monitor")

def get_ms_token(length=107):  
    chars = 'ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789='  
    return ''.join(random.choices(chars, k=length))

class AsyncDouyinLiveMonitor:
    def __init__(self, cookies: List[str], db: AsyncPostgresHandler, session=None):
        if not cookies:
            raise ValueError("必须提供至少一个Cookie")
        self.cookies = cookies
        self.current_cookie_index = 0
        self.base_url = "https://www.douyin.com"
        self.current_cookie = None
        self.current_sec_user_id = None
        is_phone_stream = False
        # 保存 DB 引用
        self.db = db
        self.session = None # 稍后在 init_session 中初始化

        self.headers = {
            'authority': 'www.douyin.com',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'cache-control': 'no-cache',
            'referer': 'https://www.douyin.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0'

        }
        self._load_current_cookie()
        self.session = session # 直接使用
    async def init_session(self):
        """【修改】引入 TCPConnector 开启 DNS 缓存，解决线程池爆炸导致的卡顿"""
        if not self.session:
            # ✅ 创建带 DNS 缓存的连接器，设置缓存 5 分钟
            connector = aiohttp.TCPConnector(
                limit=100, 
                use_dns_cache=True, 
                ttl_dns_cache=300
            )
            timeout = aiohttp.ClientTimeout(total=10)
            # ✅ 在创建 session 时传入 connector
            self.session = aiohttp.ClientSession(
                timeout=timeout, 
                connector=connector
            )
    async def close(self):
        """【修改】如果是外部传入的 session，这里什么都不做"""
        # 仅当 session 是自己内部创建时才关闭，或者干脆留给 main 关闭
        pass
    async def _reload_cookies(self):
        """【新增】从数据库热加载 Cookie"""
        if not self.db: return
        try:
            new_cookies = await self.db.get_all_cookies()
            if new_cookies:
                self.cookies = new_cookies
                # 这一步是为了防止索引越界
                if self.current_cookie_index >= len(self.cookies):
                    self.current_cookie_index = 0
                logger.info(f"🔄 [Monitor] Cookie 池已热重载，当前可用: {len(self.cookies)} 个")
            else:
                logger.warning("⚠️ [Monitor] 数据库中没有可用 Cookie！")
        except Exception as e:
            logger.error(f"❌ 热加载 Cookie 失败: {e}")
    def _load_current_cookie(self):
        self.current_cookie = self.cookies[self.current_cookie_index]
        self.headers['cookie'] = self.current_cookie
        self.current_sec_user_id = self._extract_sec_user_id(self.current_cookie)
        short_cookie = self.current_cookie[:20] + "..."
        logger.info(f"🔄 [Monitor] 已加载第 {self.current_cookie_index + 1} 个Cookie: {short_cookie}")

    def rotate_cookie(self) -> bool:
        logger.warning("⚠️ [Monitor] 当前 Cookie 可能失效，正在切换...")
        next_index = (self.current_cookie_index + 1) % len(self.cookies)
        self.current_cookie_index = next_index
        self._load_current_cookie()
        return True

    def _extract_sec_user_id(self, cookie: str) -> Optional[str]:
        try:
            match = re.search(r'MS4wLjABAAAA[^%;]*', cookie)
            if match: return match.group(0)
        except Exception: pass
        return None

    def _generate_params(self, offset: int = 0, count: int = 20) -> Dict:
        """
        保持参数完整性，复刻真实抓包
        """
        return {
            'device_platform': 'webapp',
            'aid': '6383',
            'channel': 'channel_pc_web',
            # 注意：这里硬编码了你提供的目标用户 sec_user_id
            'sec_user_id': self.current_sec_user_id or '',
            'offset': str(offset),
            'count': str(count),
            'min_time': '0',
            'max_time': '0',
            'source_type': '4',
            'gps_access': '0',
            'address_book_access': '0',
            'is_top': '1',
            'pc_client_type': '1',
            'pc_libra_divert': 'Windows',      # 【新增】系统类型
            'support_h265': '1',               # 【新增】视频编码支持
            'support_dash': '1',               # 【新增】流媒体支持
            'webcast_sdk_version': '170400',
            'webcast_version_code': '170400',  # 【新增】
            'version_code': '170400',
            'version_name': '17.4.0',          # 【新增】版本名
            'cookie_enabled': 'true',
            'screen_width': '1920',            # 【新增】屏幕宽
            'screen_height': '1080',           # 【新增】屏幕高
            'browser_language': 'zh-CN',       # 【新增】语言
            'browser_platform': 'Win32',       # 【新增】
            'browser_name': 'Chrome',          # 【新增】
            'browser_version': '144.0.0.0',    # 【新增】浏览器版本
            'browser_online': 'true',          # 【新增】
            'engine_name': 'Blink',            # 【新增】渲染引擎
            'engine_version': '144.0.0.0',     # 【新增】
            'os_name': 'Windows',              # 【新增】操作系统
            'os_version': '10',                # 【新增】系统版本
            'cpu_core_num': '16',              # 【新增】CPU核心数
            'device_memory': '8',              # 【新增】内存
            'platform': 'PC',
            'downlink': '10',                  # 【新增】下行速度模拟
            'effective_type': '4g',            # 【新增】网络类型
            'round_trip_time': '0',            # 【新增】
            'msToken': get_ms_token(),
            'a_bogus': '1',                    # 依然是手动填的1
        }

    async def get_following_list(self, offset: int = 0, count: int = 20, retry: int = 0) -> Optional[Dict]:
        """
        异步获取关注列表 (含自动淘汰和热重载逻辑)
        """
        # 防止无限递归，重试次数超过当前池子大小时停止
        if retry > len(self.cookies) + 2: # 多给2次机会给新加载的
            logger.error("❌ [Monitor] 所有 Cookie 均失效且重载无效，暂停 60秒...")
            await asyncio.sleep(60)
            # 睡醒后再试一次重载
            await self._reload_cookies()
            return None # 或者 return await self.get_following_list(...)

        if not self.session: await self.init_session()

        try:
            url = f"{self.base_url}/aweme/v1/web/user/following/list/"
            params = self._generate_params(offset, count)
            
            async with self.session.get(url, params=params, headers=self.headers) as response:
                
                # ==================== 🔴 核心修改点：处理失效 Cookie ====================
                if response.status in [401, 403]:
                    logger.warning(f"🚫 [失效] Cookie 已过期 (Status: {response.status}): {self.current_cookie[:20]}...")
                    
                    # 1. 从数据库物理删除
                    if self.db:
                        await self.db.delete_cookie(self.current_cookie)
                    
                    # 2. 从内存列表移除当前失效的
                    if self.current_cookie in self.cookies:
                        self.cookies.remove(self.current_cookie)

                    # 3. 尝试从数据库加载新的 (可能你在后台刚加了新的)
                    await self._reload_cookies()
                    
                    # 4. 如果池子空了，报错
                    if not self.cookies:
                        logger.error("❌ Cookie 池已空！请去后台添加！")
                        return None

                    # 5. 切换到下一个 (reload_cookies 内部处理了索引，这里直接 load 即可)
                    self._load_current_cookie() 
                    
                    # 6. 重试
                    return await self.get_following_list(offset, count, retry + 1)
                # ===================================================================

                try:
                    text_data = await response.text()
                    json_data = json.loads(text_data)
                    
                    # 业务状态码检查 (有时候 HTTP 200 但返回未登录)
                    if 'status_code' in json_data and json_data['status_code'] != 0:
                        # 某些 status_code 可能也是 cookie 失效，如果不确定可以保守处理只切换不删除
                        # 或者如果你确定是失效，也可以在这里调用 delete_cookie
                        logger.warning(f"⚠️ API 业务错误: {json_data.get('status_msg')}")
                        self.rotate_cookie()
                        return await self.get_following_list(offset, count, retry + 1)
                    
                    return json_data
                except json.JSONDecodeError:
                    logger.warning("⚠️ JSON 解析失败")
                    self.rotate_cookie()
                    return await self.get_following_list(offset, count, retry + 1)
                    
        except Exception as e:
            logger.error(f"❌ [Monitor] 请求异常: {e}")
            self.rotate_cookie()
            return await self.get_following_list(offset, count, retry + 1)

    async def get_all_live_users(self) -> List[Dict]:
        """
        异步扫描所有关注用户
        """
        live_users = []
        offset = 0
        page = 1
        
        await self.init_session()
        
        while True:
            data = await self.get_following_list(offset, 20)
            if not data or 'followings' not in data:
                break
            
            for user in data['followings']:
                # 1. 异步保存/更新 Author 资料卡
                await self._save_author_card(user)

                # 2. 更新 Room 实时状态 (存库逻辑不变，status=2 也会存)
                if self.db:
                    follower_count = user.get('follower_count', 0)
                    live_status = user.get('live_status', 0)
                    room_id = None
                    if live_status == 1:
                        room_id = user.get('room_id_str')
                    if not room_id and user.get('room_data'):
                        try:
                            rd = json.loads(user.get('room_data'))
                            room_id = rd.get('id_str') or rd.get('room_id_str')
                        except: pass
                    
                    # 🟢 这里会把 status=2 也存进数据库，满足你的需求
                    if room_id:
                        await self.db.update_room_realtime(str(room_id), live_status, follower_count)

                # 3. 提取直播列表 (准备返回给 Main)
                # 🟢 [核心修改]：严格过滤，只有 status=1 才提取
                # 原来的逻辑是 if user.get('live_status') in [1, 2]:
                
                raw_status = user.get('live_status', 0)
                
                if raw_status == 1:  # 👈 只允许 status=1 进入待录制列表
                    live_info = self.extract_live_info(user)
                    
                    if live_info:
                        # 兜底补全 web_rid
                        if not live_info.get('web_rid') and self.db:
                            sec_uid = live_info.get('sec_uid')
                            if sec_uid:
                                try:
                                    author_doc = await self.db.db['authors'].find_one(
                                        {"sec_uid": sec_uid}, 
                                        {"self_web_rid": 1}
                                    )
                                    if author_doc and author_doc.get('self_web_rid'):
                                        live_info['web_rid'] = author_doc['self_web_rid']
                                        logger.info(f"♻️ [Monitor] 已补全 web_rid: {live_info['nickname']}")
                                except Exception: pass

                        if live_info.get('web_rid'):
                            live_users.append(live_info)
                        else:
                            logger.warning(f"⚠️ [Monitor] 放弃任务 (无 web_rid): {live_info.get('nickname')}")
                

            # --- 翻页判断 ---
            has_more = data.get('has_more', False)
            if not has_more:
                break
            
            offset += 20
            page += 1
            await asyncio.sleep(2.0)

        return live_users

    async def _save_author_card(self, user_data: Dict):
        """异步保存主播资料卡"""
        if not self.db: return
        try:
            nickname = user_data.get('nickname')
            sec_uid = user_data.get('sec_uid')
            uid = user_data.get('uid')
            signature = user_data.get('signature')
            live_status = user_data.get('live_status', 0)            
            avatar_url = ""
            try:
                if user_data.get('avatar_thumb') and user_data['avatar_thumb'].get('url_list'):
                    avatar_url = user_data['avatar_thumb']['url_list'][0]
            except Exception: pass
                       
            web_rid = None
            user_count = 0
            weight = 3
            
            # ✅ 修复点：在 if 外面提前获取并初始化 raw_room_data
            raw_room_data = user_data.get('room_data') 
            
            if live_status in [1, 2]:
                weight = live_status
                # ✅ 这里直接使用提前获取好的 raw_room_data 即可
                if raw_room_data:
                    try:
                        room_data_dict = json.loads(raw_room_data)
                        user_count = room_data_dict.get('user_count', 0)
                        web_rid = room_data_dict.get('owner', {}).get('web_rid')
                    except Exception: pass
                if not web_rid: 
                    web_rid = user_data.get('web_rid')
            else:
                web_rid = None
                user_count = 0

            # 1. 先构建基础字典，不包含 self_web_rid
            author_doc = {
                'nickname': nickname,
                'sec_uid': sec_uid,
                'uid': uid,
                'avatar': avatar_url,
                'signature': signature,
                'live_status': live_status,
                'web_rid': web_rid,
                'user_count': user_count,
                'follower_count': user_data.get('follower_count', 0),
                'weight': weight
            }

            if live_status == 1 and web_rid:
                author_doc['self_web_rid'] = web_rid

            # --- 修改结束 ---

            # 异步写入 (db.py 不需要改，因为它使用的是 $set)
            await self.db.save_author_card(author_doc)
        except Exception as e:
            logger.error(f"⚠️ 保存资料卡异常: {e}")

    def extract_live_info(self, user_data: Dict) -> Optional[Dict]:
        """
        提取直播信息（含详细调试日志）
        """
        try:
            live_status = user_data.get('live_status')
            room_data_dict = {}
            web_rid = None
            is_phone_stream = False  # ✅ 新增：默认当做非手机开播
            
            # 尝试解析 room_data
            raw_room_data = user_data.get('room_data')
            if raw_room_data:
                try:
                    room_data_dict = json.loads(raw_room_data)
                    # 路径 1: room_data -> owner -> web_rid
                    web_rid = room_data_dict.get('owner', {}).get('web_rid')
                    
                    if room_data_dict.get('live_type_normal') is True or room_data_dict.get('live_type_audio') is True:
                        # 手机视频直播 或 手机语音直播，都打上手机端标签
                        is_phone_stream = True
                    elif room_data_dict.get('live_type_third_party') is True:
                        # 电脑第三方 OBS 推流
                        is_phone_stream = False
                        
                except: pass
            
            # 路径 2: user_data -> web_rid
            if not web_rid: 
                web_rid = user_data.get('web_rid')

            # ==================== 🔍 调试日志核心区 ====================
            if not web_rid:
                nickname = user_data.get('nickname', '未知用户')
                logger.warning(f"🕵️ [调试] 发现无 web_rid 样本: {nickname} (LiveStatus: {live_status})")
                
                if raw_room_data:
                    # 打印完整的 room_data，方便你复制出来分析结构
                    logger.warning(f"📜 [调试] room_data 原始内容: {raw_room_data}")
                    
                    # 顺便帮你检查一下是否有疑似 ID 的其他字段
                    # 有时候 id_str 其实就是 web_rid
                    candidate_id = room_data_dict.get('id_str')
                    if candidate_id:
                        logger.warning(f"💡 [提示] 发现 room_data.id_str: {candidate_id}，也许它是 web_rid？")
                else:
                    # 如果连 room_data 都没有，打印 user_data 的一级 Key，看看都有什么
                    keys_list = list(user_data.keys())
                    logger.warning(f"🈳 [调试] 该用户没有 room_data 字段！User Keys: {keys_list}")
            # ==========================================================

            room_id = None
            if live_status == 1:
                room_id = user_data.get('room_id_str')          
            if not room_id and room_data_dict:
                room_id = room_data_dict.get('id_str')

            avatar_url = ""
            if user_data.get('avatar_thumb') and user_data['avatar_thumb'].get('url_list'):
                avatar_url = user_data['avatar_thumb']['url_list'][0]
            
            return {
                'nickname': user_data.get('nickname', '未知'),
                'uid': user_data.get('uid'),
                'sec_uid': user_data.get('sec_uid'),
                'live_status': live_status,
                'room_id': room_id, 
                'web_rid': web_rid, 
                'is_phone_stream': is_phone_stream,
                'title': user_data.get('signature', '')[:30],
                'follower_count': user_data.get('follower_count', 0),
                'avatar_url': avatar_url,
                'cover_url': avatar_url,
                'title': f"{user_data.get('nickname', '主播')}正在直播"
            }
        except Exception as e:
            logger.error(f"❌ 解析直播信息异常: {e}")
            return None
    async def delete_cookie(self, cookie_str: str):
        """将处理逻辑全权交接给 DB 层"""
        if not cookie_str or not self.db: 
            return
        await self.db.delete_cookie(cookie_str)
            
            