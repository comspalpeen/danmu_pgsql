# fetcher.py
import gzip
import logging
import asyncio
import aiohttp
import urllib.parse
import orjson as json
import random
from datetime import datetime
from protobuf import douyin_pb2  # ✅ 官方库

from src.utils.fetcher_utils import (
    generateSignature, 
    generateMsToken, 
    get_safe_url, 
    get_ac_signature, 
    get_js_context    # ✅ 引入新的线程安全方法
)

#from src.db.db import AsyncPostgresHandler
#from src.core.gift_deduplicator import AsyncGiftDeduplicator
from src.core.message_handler import MessageHandler

logger = logging.getLogger("fetcher")

class AsyncDouyinLiveWebFetcher:
    
    def __init__(self, live_id, db, gift_processor, start_follower_count=0, abogus_file='js/a_bogus.js', initial_state=None, session=None):

        self.live_id = live_id
        self.start_follower_count = start_follower_count
        self.abogus_file = abogus_file
        self.db = db
        self.gift_processor = gift_processor
        self.handler = None 
        self.initial_state = initial_state       
        
        self.session = None 
        self.ws = None      
        
        self.__ttwid = None
        self.current_room_id = None
        
        self.live_url = "https://live.douyin.com/"
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.headers = {'User-Agent': self.user_agent}
        
        self.running = False
        self.session = session 
        self._own_session = False 
        
        if self.session is None:
            # ✅ 这里也要加 DNS 缓存
            connector = aiohttp.TCPConnector(limit=100, use_dns_cache=True, ttl_dns_cache=300)
            self.session = aiohttp.ClientSession(headers=self.headers, connector=connector)
            self._own_session = True

    async def get_ttwid(self):
        if self.__ttwid: return self.__ttwid
        
        if self.session:
            for cookie in self.session.cookie_jar:
                if cookie.key == 'ttwid':
                    self.__ttwid = cookie.value
                    return self.__ttwid
        try:
            async with self.session.get(self.live_url, headers=self.headers) as resp:
                pass
            for cookie in self.session.cookie_jar:
                if cookie.key == 'ttwid':
                    self.__ttwid = cookie.value
                    return self.__ttwid
        except Exception as err:
            logger.error(f"【X】获取游客 ttwid 失败: {err}")
        return None

    def get_ac_nonce(self):
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return ''.join(random.choice(chars) for _ in range(21))
    
    async def get_a_bogus(self, url_params: dict):
        url = urllib.parse.urlencode(url_params)
        
        def _calc():
            # ✅ 获取当前专属线程的 JS 引擎，绝对不会发生多线程打架
            ctx = get_js_context(self.abogus_file)
            return ctx.call("get_ab", url, self.user_agent)
            
        # 依然丢给底层线程池去算，彻底解放 asyncio 主循环！
        return await asyncio.to_thread(_calc)
    async def get_room_status(self):
        try:
            ttwid = await self.get_ttwid()
            msToken = generateMsToken()
            nonce = self.get_ac_nonce()
            signature = get_ac_signature(self.live_url[8:], nonce, self.user_agent)

            base_url = "https://live.douyin.com/webcast/room/web/enter/"
            params = {
                'aid': '6383',
                'app_name': 'douyin_web',
                'live_id': '1',
                'device_platform': 'web',
                'language': 'zh-CN',
                'enter_from': 'page_refresh',
                'cookie_enabled': 'true',
                'screen_width': '1920',
                'screen_height': '1080',
                'browser_language': 'zh-CN',
                'browser_platform': 'Win32',
                'browser_name': 'Edge',
                'browser_version': '120.0.0.0',
                'web_rid': self.live_id,
                'room_id_str': "",
                'enter_source': '',
                'is_need_double_stream': 'false',
                'insert_task_id': '',
                'live_reason': '',
                'msToken': msToken,
            }

            try:
                params['a_bogus'] = await self.get_a_bogus(params)
            except Exception as e:
                pass

            headers = self.headers.copy()
            headers.update({'Referer': f'https://live.douyin.com/{self.live_id}'})
            
            req_cookies = {
                                '__ac_nonce': nonce,
                                '__ac_signature': signature,
                                'msToken': msToken,
                                'ttwid': ttwid  # <--- 加上这一行，变量就不再是暗的了
                            }

            async with self.session.get(base_url, params=params, headers=headers, cookies=req_cookies, timeout=10) as resp:
                text = await resp.text() 
                try:
                    json_data = json.loads(text)
                except json.JSONDecodeError:
                    return None
            
            data_core = json_data.get('data')
            if not data_core: return None

            room_data = None
            if isinstance(data_core.get('data'), list) and len(data_core.get('data')) > 0:
                room_data = data_core.get('data')[0]
            elif isinstance(data_core.get('user'), dict):
                room_data = data_core
            
            if not room_data: return None
            
            status = room_data.get('status')
            user = room_data.get('owner') or room_data.get("user")
            if not user: return None

            self.current_room_id = room_data.get('id_str')
            logger.info
            info = {
                'web_rid': self.live_id,
                'room_id': self.current_room_id,
                'title': room_data.get('title', ''),
                'user_id': user.get('id_str', ''),
                'sec_uid': user.get('sec_uid', ''),
                'nickname': user.get('nickname', '未知用户'),
                'avatar_url': get_safe_url(user.get('avatar_thumb')),
                'cover_url': get_safe_url(room_data.get('cover')),
                'user_count': room_data.get('user_count', 0), 
                'like_count': room_data.get('like_count', 0),
                'room_status': status,
                'live_status': 1,
                'start_follower_count': self.start_follower_count
            }
            logger.info(f"🟢 [LiveMan] 直播中 | 🏠 {info['nickname']}: {info['title']}")
            if self.db: await self.db.save_room_info(info)
            return info

        except Exception as e:
            logger.error(f"❌ 获取直播间状态异常: {e}")
            return None

    async def start(self):
        logger.info(f"🚀 启动抓取: {self.live_id}")
        self.running = True
        
        try:
            if self.initial_state and self.initial_state.get('room_id'):
                logger.info(f"⚡ [极速模式] 使用 Monitor 数据直接启动: {self.live_id}")
                self.current_room_id = self.initial_state['room_id']
                
                temp_info = {
                    'web_rid': self.live_id,
                    'room_id': self.current_room_id,
                    'title': self.initial_state.get('title') or f"{self.initial_state.get('nickname', '主播')}正在直播",
                    'user_id': self.initial_state.get('uid', ''),
                    'sec_uid': self.initial_state.get('sec_uid', ''),
                    'nickname': self.initial_state.get('nickname', '未知用户'),
                    'cover_url': self.initial_state.get('cover_url') or self.initial_state.get('avatar_url', ''),
                    'avatar_url': self.initial_state.get('avatar_url', ''),
                    'live_status': 1, 
                    'start_follower_count': self.start_follower_count,
                    'created_at': datetime.now()
                }
                
                if self.db:
                    await self.db.save_room_info(temp_info)
                    
                asyncio.create_task(self._lazy_update_room_info())

            else:
                room_info = await self.get_room_status()
                if not room_info:
                    logger.warning("⚠️ 等待 3秒 后重试...")
                    await asyncio.sleep(3)
                    room_info = await self.get_room_status()
                    
                if not room_info:
                    logger.error("❌ 无法获取房间信息，放弃录制")
                    return

            self.handler = MessageHandler(
                live_id=self.live_id,
                room_id=self.current_room_id,
                db=self.db,
                gift_processor=self.gift_processor
            )

            await self._connectWebSocket()
            
        except Exception as e:
            logger.error(f"❌ 录制任务异常退出: {e}")
        finally:
            await self.stop()

    async def stop(self):
        self.running = False
        if self.ws: await self.ws.close()
        
        if self._own_session and self.session:
            await self.session.close()

    async def _sendHeartbeat(self, ws):
        while self.running and not ws.closed:
            try:
                heartbeat = douyin_pb2.PushFrame()
                heartbeat.payloadType = 'hb'  # ✅ 严格遵守 proto 文件的驼峰命名
                await ws.send_bytes(heartbeat.SerializeToString()) 
                await asyncio.sleep(20)
            except asyncio.CancelledError:  
                break
            except Exception as e: 
                logger.debug(f"⚠️ [LiveMan] 心跳异常: {e}")
                break

    async def _handle_binary_message(self, data, ws):
        try:
            package = douyin_pb2.PushFrame()
            package.ParseFromString(data)
            
            response = douyin_pb2.Response()
            response.ParseFromString(gzip.decompress(package.payload))
            
            if response.needAck:  # ✅ needAck 驼峰命名
                ack = douyin_pb2.PushFrame()
                ack.logId = package.logId  # ✅ logId 驼峰命名
                ack.payloadType = 'ack'    # ✅ payloadType 驼峰命名
                ack.payload = response.internalExt.encode('utf-8')  # ✅ internalExt 驼峰命名
                await ws.send_bytes(ack.SerializeToString())
            
            for msg in response.messagesList:  # ✅ messagesList 驼峰命名
                if self.handler:
                    is_ended = await self.handler.handle(msg.method, msg.payload)
                    if is_ended:
                        self.running = False
                        await ws.close()
                        break
        except Exception as e: 
            pass

    async def _connectWebSocket(self):
        ttwid = await self.get_ttwid() or ""
        
        wss = ("wss://webcast100-ws-web-lq.douyin.com/webcast/im/push/v2/?app_name=douyin_web"
               "&version_code=180800&webcast_sdk_version=1.0.14-beta.0"
               "&update_version_code=1.0.14-beta.0&compress=gzip&device_platform=web&cookie_enabled=true"
               "&screen_width=1536&screen_height=864&browser_language=zh-CN&browser_platform=Win32"
               "&browser_name=Mozilla"
               "&browser_version=5.0%20(Windows%20NT%2010.0;%20Win64;%20x64)%20AppleWebKit/537.36%20(KHTML,"
               "%20like%20Gecko)%20Chrome/126.0.0.0%20Safari/537.36"
               "&browser_online=true&tz_name=Asia/Shanghai"
               f"&cursor=d-1_u-1_fh-7392091211001140287_t-1721106114633_r-1"
               f"&internal_ext=internal_src:dim|wss_push_room_id:{self.current_room_id}|wss_push_did:7319483754668557238"
               f"|first_req_ms:1721106114541|fetch_time:1721106114633|seq:1|wss_info:0-1721106114633-0-0|"
               f"wrds_v:7392094459690748497"
               f"&host=https://live.douyin.com&aid=6383&live_id=1&did_rule=3&endpoint=live_pc&support_wrds=1"
               f"&user_unique_id=7319483754668557238&im_path=/webcast/im/fetch/&identity=audience"
               f"&need_persist_msg_count=15&insert_task_id=&live_reason=&room_id={self.current_room_id}&heartbeatDuration=0")
        
        signature = generateSignature(wss)
        wss += f"&signature={signature}"
        
        strategies = []
        
        # ✅ 新增：从 initial_state 获取 Monitor 传过来的开播类型标志
        is_phone_stream = False
        if self.initial_state:
            is_phone_stream = self.initial_state.get('is_phone_stream', False)

        # ✅ 取消硬编码白名单，改为动态判断
        if is_phone_stream and self.db:
            try:
                real_cookies = await self.db.get_all_cookies()
                if real_cookies:
                    selected_cookie = random.choice(real_cookies)
                    strategies.append({
                        "name": f"RealCookie(Phone Stream | Pool:{len(real_cookies)})",
                        "headers": {
                            "Cookie": selected_cookie,
                            "User-Agent": self.user_agent
                        }
                    })
            except Exception as e:
                pass

        # ✅ 兜底策略：第三方推流，或者手机推流但没拿到真实 Cookie 时，使用 ttwid
        strategies.append({
            "name": "Default(TTWID)",
            "headers": {
                "Cookie": f"ttwid={ttwid}",
                "User-Agent": self.user_agent
            }
        })

        try:
            for strategy in strategies:
                mode_name = strategy['name']
                headers = strategy['headers']

                try:
                    async with self.session.ws_connect(wss, headers=headers, timeout=15) as ws:
                        self.ws = ws
                        logger.info(f"✅ WebSocket 连接成功 [{mode_name}]")
                        
                        hb_task = asyncio.create_task(self._sendHeartbeat(ws))
                        
                        try:
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.BINARY:
                                    await self._handle_binary_message(msg.data, ws)
                                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                    logger.warning(f"⚠️ WebSocket 连接被动关闭 [{mode_name}]")
                                    break
                        except Exception as e:
                            logger.error(f"❌ 消息读取循环异常 [{mode_name}]: {e}")
                        
                        if hb_task:
                            hb_task.cancel()
                            try:
                                await hb_task
                            except:
                                pass
                        
                        return 

                except Exception as e:
                    continue

            logger.error(f"❌ 所有 WebSocket 连接策略均失败: {self.live_id}")
            
        finally:
            self.running = False 
            if self.ws and not self.ws.closed:
                await self.ws.close()
            logger.info(f"👋 [LiveMan] 录制任务结束/退出: {self.live_id}")

    async def _lazy_update_room_info(self):
        try:
            for i in range(3):
                if not self.running: break
                
                wait_time = 10 + (i * 5)
                await asyncio.sleep(wait_time)
                room_info = await self.get_room_status()
                
                if room_info:
                    break 
        except Exception:
            pass