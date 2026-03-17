# message_handler.py
import time
import logging

from protobuf import douyin_pb2  # ✅ 官方 Google Protobuf

logger = logging.getLogger("MsgHandler")

def _get_safe_url(icon_obj):
    """专门为 Google Protobuf 强化的 URL 提取器"""
    if not icon_obj: 
        return ""
    try:
        if hasattr(icon_obj, 'urlListList') and len(icon_obj.urlListList) > 0:
            return icon_obj.urlListList[0]
        if hasattr(icon_obj, 'url_list_list') and len(icon_obj.url_list_list) > 0:
            return icon_obj.url_list_list[0]
    except Exception:
        pass
    return ""

def _extract_user_info(user, current_live_id=""):
    """
    🥇 终极版：统一提取用户信息
    智能兼容新旧版本，优先从 61 号字段 (NewBadgeImageList) 提取勋章和等级
    """
    info = {
        'user_id': str(user.id),
        'user_name': user.nickName,
        'gender': user.gender,
        'sec_uid': user.secUid,
        'display_id':user.displayId,
        'avatar_url': _get_safe_url(user.AvatarThumb),
        'pay_grade': 0,
        'pay_grade_icon': "",
        'fans_club_level': 0,
        'fans_club_icon': ""
    }
    
    # --- 1. 旧版字段兜底 (防止老残旧客户端断供 61 字段) ---
    if user.HasField('PayGrade'):
        info['pay_grade'] = user.PayGrade.level
        info['pay_grade_icon'] = _get_safe_url(user.PayGrade.newImIconWithLevel)
    
    if user.HasField('FansClub') and user.FansClub.HasField('data'):
        if 4 in user.FansClub.data.badge.icons:
            info['fans_club_icon'] = _get_safe_url(user.FansClub.data.badge.icons[4])
        info['fans_club_level'] = user.FansClub.data.level

    # --- 2. 核心：从 61 号字段提取并强覆盖 ---
    for badge in user.NewBadgeImageList:
        # imageType == 1: 财富等级
        if badge.imageType == 1:
            info['pay_grade'] = badge.content.level
            info['pay_grade_icon'] = _get_safe_url(badge)
            
        # imageType == 7 / 51: 粉丝团高等级灯牌
        # imageType == 35: 粉丝团基础灯牌
        elif badge.imageType in (7, 51):
            if badge.content.level > 0:
                info['fans_club_level'] = badge.content.level
            
            # 51 通常是高清 xmp 动效格式，遇到 51 强制更新 icon
            if not info['fans_club_icon'] or badge.imageType == 51:
                info['fans_club_icon'] = _get_safe_url(badge)
    if str(current_live_id) == "615189692839":
        info['cz_club_level'] = info.get('fans_club_level', 0)
    else:
        info['cz_club_level'] = 0           
    return info

class MessageHandler:
    def __init__(self, live_id, room_id, db, gift_processor):
        self.live_id = live_id
        self.room_id = room_id
        self.db = db
        self.gift_processor = gift_processor
        self.last_seq_state = None       
       # self.last_like_time = 0
        self.last_seq_time = 0
        self.THROTTLE_INTERVAL = 1 
        self.vip_users_cache = {}
    async def handle(self, method, payload):
        try:
            if method == 'WebcastChatMessage':
                await self._parse_chat(payload)
            elif method == 'WebcastGiftMessage':
                await self._parse_gift(payload)
            elif method == 'WebcastRoomUserSeqMessage':
                await self._parse_user_seq(payload)
            elif method == 'WebcastLikeMessage':
                await self._parse_like(payload)
            elif method == 'WebcastMemberMessage':  # ✅ 进场消息
                await self._parse_member(payload)
            elif method == 'WebcastControlMessage':
                return await self._parse_control(payload)
            elif method == 'WebcastLinkMicBattleFinishMethod':
                await self._parse_pk_finish(payload)
            elif method == 'WebcastScreenChatMessage':
                await self._parse_screen_chat(payload)
            elif method == 'WebcastPrivilegeScreenChatMessage':
                await self._parse_privilege_screen_chat(payload)
            # elif method == 'WebcastLinkMicMethod':  # ✅ 新增实时 PK 状态/分数入口
            #     await self._parse_link_mic_method(payload)
            # elif method in ('WebcastLinkMicBattle', 'WebcastLinkMicBattleMethod'):  # ✅ 新增 PK 开始入口
            #     await self._parse_pk_start(payload)
            elif method == 'WebcastFansclubMessage':
                await self._parse_fansclub(payload)
            elif method == 'WebcastSocialMessage':
                await self._parse_social(payload)
        except Exception as e:
            logger.error(f"⚠️ 消息分发解析异常 [{method}]: {e}", exc_info=True)
        return False


    async def _parse_control(self, payload):
        try:
            message = douyin_pb2.ControlMessage()
            message.ParseFromString(payload)
            if message.status == 3:
                logger.info(f"🛑 [ControlMsg] 收到下播信号 (Room: {self.room_id})")
                if self.db and self.room_id:
                    await self.db.set_room_ended(self.room_id)
                return True 
        except Exception as e: 
            logger.error(f"❌ 解析 Control 异常: {e}", exc_info=True)
        return False

    async def _parse_chat(self, payload):
        try:
            message = douyin_pb2.ChatMessage()
            message.ParseFromString(payload)
            
            # ✅ 一行代码提取所有用户属性，干掉冗长逻辑
            user_info = _extract_user_info(message.user, self.live_id)
            
            event_ts = message.eventTime
            event_time_val = event_ts if event_ts > 0 else time.time()
            
            chat_data = {
                'web_rid': self.live_id,
                'room_id': self.room_id,
                'content': message.content,
                'event_time': event_time_val,
                'created_at': time.time()
            }
            chat_data.update(user_info) # 合并用户字典
            
            if self.db: 
                await self.db.insert_chat(chat_data)
        except Exception as e: 
            logger.error(f"❌ 解析弹幕异常: {e}", exc_info=True)

    async def _parse_gift(self, payload):
        try:
            message = douyin_pb2.GiftMessage()
            message.ParseFromString(payload)
            gift = message.gift
            
            # ✅ 一行代码完成用户提取
            user_info = _extract_user_info(message.user, self.live_id)
            
            repeat_count = message.repeatCount
            combo_count = message.comboCount
            group_count = message.groupCount
            diamond_count = gift.diamondCount
            # ✅ 维持原有连击逻辑 (将倍数转移给 combo_count)
            if repeat_count > 0:
                combo_count = repeat_count
                group_count = 1
            
            send_time_ms = message.sendTime if message.sendTime > 0 else int(time.time() * 1000)
            
            gift_data = {
                'web_rid': self.live_id,
                'room_id': self.room_id,
                'gift_icon_url': _get_safe_url(gift.icon),
                'gift_id': str(gift.id),
                'gift_name': gift.name,
                'diamond_count': diamond_count,
                'combo_count': combo_count,
                'group_count': group_count,
                'repeat_count': repeat_count,
                'group_id': str(message.groupId),
                'repeat_end': message.repeatEnd,
                'trace_id': message.traceId,
                'send_time': send_time_ms / 1000.0,
                'created_at': time.time()
            }
            gift_data.update(user_info) # 合并用户字典
            
            if self.gift_processor: 
                await self.gift_processor.process_gift(gift_data)
        except Exception as e: 
            logger.error(f"❌ 解析礼物异常: {e}", exc_info=True)

    async def _parse_screen_chat(self, payload):
        try:
            msg = douyin_pb2.ScreenChatMessage()
            msg.ParseFromString(payload)
            if not msg.HasField('user') or not msg.content: return
            
            user_info = _extract_user_info(msg.user, self.live_id)
            
            chat_data = {
                "web_rid": self.live_id,
                "room_id": str(self.room_id),
                "content": f"[房管飘屏] {msg.content}",
                "event_time": time.time(),
                "created_at": time.time()
            }
            chat_data.update(user_info)
            
            if self.db:
                await self.db.insert_chat(chat_data)
        except Exception as e:
            logger.error(f"❌ 解析房管飘屏异常: {e}", exc_info=True)

    async def _parse_privilege_screen_chat(self, payload):
        try:
            msg = douyin_pb2.WebcastPrivilegeScreenChatMessage()
            msg.ParseFromString(payload)
            if not msg.HasField('user') or not msg.content: return
            
            user_info = _extract_user_info(msg.user, self.live_id)
            
            chat_data = {
                "web_rid": self.live_id,
                "room_id": str(self.room_id),
                "content": f"[特权飘屏] {msg.content}",
                "event_time": time.time(),  
                "created_at": time.time()
            }
            chat_data.update(user_info)
            
            if self.db:
                await self.db.insert_chat(chat_data)
        except Exception as e:
            logger.error(f"❌ 解析特权飘屏异常: {e}", exc_info=True)

    async def _parse_user_seq(self, payload):
        now = time.time()
        if now - self.last_seq_time < self.THROTTLE_INTERVAL: return
        time_diff = now - self.last_seq_time if self.last_seq_time > 0 else 0
        self.last_seq_time = now

        try:
            message = douyin_pb2.RoomUserSeqMessage()
            message.ParseFromString(payload)
            stats = {'user_count': message.total, 'total_user': message.totalUser}
            inc_data = {}
            if self.last_seq_state:
                inc_data = {'total_watch_time_sec': message.total * time_diff}
            self.last_seq_state = {'online': message.total, 'total': message.totalUser, 'time': now}

            if self.db and self.room_id:
                await self.db.update_room_stats(self.room_id, stats)
                if inc_data: await self.db.increment_room_stats(self.room_id, inc_data)
        except Exception as e:
            logger.error(f"⚠️ 解析 UserSeq 异常: {e}", exc_info=True)

    async def _parse_like(self, payload):
   #     now = time.time()
   #     if now - self.last_like_time < self.THROTTLE_INTERVAL: return
   #    self.last_like_time = now

        try:
            message = douyin_pb2.LikeMessage()
            message.ParseFromString(payload)
            
            # ✅ 新增：提取用户信息并进行 VIP 检查
            if message.HasField('user'):
                user_info = _extract_user_info(message.user, self.live_id)
                await self._check_and_save_vip(user_info)

            # (原有的点赞总数更新逻辑保持不变)
            if self.db and self.room_id:
                await self.db.update_room_stats(self.room_id, {'like_count': message.total})
        except Exception as e: 
            logger.error(f"❌ 解析点赞异常: {e}", exc_info=True)

    async def _parse_pk_finish(self, payload):
        # (保持你原有的 PK 结算解析逻辑完全不变)
        try:
            message = douyin_pb2.LinkMicBattleFinishMethod()
            message.ParseFromString(payload)
            if message.info.status != 2: return

            battle_id = str(message.info.battle_id)
            channel_id = str(message.info.channel_id)
            duration = str(message.info.duration)
            start_time_ms = message.info.start_time_ms
            start_time_val = start_time_ms / 1000.0 if start_time_ms > 0 else time.time()
            scores_map = {}
            has_valid_win_status = False
            
            for s in message.scores:
                uid = str(s.user_id)
                win_status = s.win_status
                if win_status in [1, 2]: has_valid_win_status = True
                scores_map[uid] = {"score": s.score, "win_status": win_status, "rank": s.rank}

            contrib_map = {}
            for c_group in message.contributors:
                anchor_id = str(c_group.anchor_id)
                top_list = []
                for item in c_group.list[:3]: 
                    top_list.append({
                        "user_id": str(item.id),
                        "nickname": item.nickname,
                        "avatar": _get_safe_url(item.avatar),
                        "score": item.score,
                        "rank": item.rank if item.rank else 0
                    })
                contrib_map[anchor_id] = top_list

            total_anchors = 0
            for army in message.anchors: total_anchors += len(army.list)

            mode_type = "team_battle" if (has_valid_win_status or total_anchors == 2) else "free_for_all"

            teams_map = {} 
            for army in message.anchors:
                for anchor_item in army.list:
                    if not anchor_item.HasField('user'): continue
                    uid = str(anchor_item.user.id)
                    score_info = scores_map.get(uid, {})
                    contributors = contrib_map.get(uid, [])
                    
                    anchor_data = {
                        "user_id": uid,
                        "nickname": anchor_item.user.nickname,
                        "avatar": _get_safe_url(anchor_item.user.avatar_thumb),
                        "score": score_info.get("score", 0),
                        "rank": score_info.get("rank", 0),
                        "contributors": contributors
                    }

                    team_id = str(score_info.get("win_status")) if has_valid_win_status else uid

                    if team_id not in teams_map:
                        teams_map[team_id] = {"team_id": team_id, "win_status": score_info.get("win_status", 0), "anchors": []}
                    teams_map[team_id]["anchors"].append(anchor_data)

            final_teams = list(teams_map.values())
            if mode_type == "free_for_all":
                final_teams.sort(key=lambda t: t["anchors"][0]["rank"] if t["anchors"] else 999)

            pk_result = {
                "battle_id": battle_id, "room_id": self.room_id, "channel_id": channel_id,
                "start_time": start_time_val, "duration": duration, "mode": mode_type, 
                "created_at": time.time(), "teams": final_teams
            }
            if self.db: await self.db.save_pk_result(pk_result)
        except Exception as e:
            logger.error(f"❌ 解析 PK 结算异常: {e}", exc_info=True)

    async def _parse_link_mic_method(self, payload):
        """
        解析 PK 实时过程数据 (分数更新、状态变更等)
        当前仅做日志打印，不存入数据库，用于测试分析
        """
        try:
            message = douyin_pb2.LinkMicMethod()
            message.ParseFromString(payload)
           # logger.info(f"{message}")
            # 如果 user_scores 为空，说明这是一条不带分数的纯状态控制消息（比如麦克风开关等），直接跳过
            if not message.user_scores:
                return
                
            channel_id = message.channel_id
            msg_type = message.message_type
            
            # 收集所有参战主播的实时分数
            score_logs = []
            for score_info in message.user_scores:
                uid = score_info.user_id
                score = score_info.score
                team_score = score_info.multi_pk_team_score
                rank = score_info.battle_rank
                
                # 拼接单人/单队的分数详情
                score_logs.append(f"[UID:{uid} 个人分:{score} 团队分:{team_score} 排名:{rank}]")
            
            # 聚合打印
            scores_str = " VS ".join(score_logs)
         #   logger.info(f"⚔️ [PK实时战况] BattleID:{channel_id} | Type:{msg_type} | 实时得分: {scores_str}")
            
        except Exception as e:
            logger.error(f"❌ 解析 PK实时分数(LinkMicMethod) 异常: {e}", exc_info=True)

    async def _parse_pk_start(self, payload):
        """
        解析 PK 开始包 (LinkMicBattle)
        抓取对阵双方/多方的主播阵容和基础配置
        """
        try:
            message = douyin_pb2.LinkMicBattle()
            message.ParseFromString(payload)
            
            info = message.info
            battle_id = info.battle_id
            channel_id = info.channel_id
            duration = info.duration
            
            # 解析参战阵容 (anchors 数组)
            teams = []
            for army in message.anchors:
                team_anchors = []
                # army.list 里面是这个阵营里所有的主播
                for item in army.list:
                    if item.HasField('user'):
                        uid = item.user.id
                        nickname = item.user.nickname
                        team_anchors.append(f"{nickname}({uid})")
                
                if team_anchors:
                    # 如果是 1v3，这里的 team_anchors 会有 3 个主播，用 '&' 连起来
                    teams.append(" & ".join(team_anchors))
                    
            # 把各个阵营用 ' VS ' 连起来
            matchup_str = " VS ".join(teams)
            
          # logger.info(f"🎬 [PK正式开始] BattleID:{battle_id} | Channel:{channel_id} | 时长:{duration}秒 | 阵容: {matchup_str}")
            
        except Exception as e:
            logger.error(f"❌ 解析 PK开始包(LinkMicBattle) 异常: {e}", exc_info=True)
    async def _check_and_save_vip(self, user_info):
        """核心逻辑：检查是否是 12 级以上大哥，并做内存防抖"""
        fans_level = user_info.get('fans_club_level', 0)
        pay_grade = user_info.get('pay_grade', 0)
        
        #  判定条件：粉丝团 >= 10 级
        if fans_level >= 10:
            uid = user_info.get('user_id')
            now = time.time()
            
            # ⏳ 内存防抖：同一个大哥，每 5 分钟（300秒）内只触发一次数据库更新
            last_record_time = self.vip_users_cache.get(uid, 0)
            if now - last_record_time > 300:
                self.vip_users_cache[uid] = now
                #logger.info(f"💎 [VIP捕捉] 发现潜水大哥! {user_info.get('user_name')} (灯牌:{fans_level}级, 财富:{pay_grade}级)")
                
                # 扔给数据库处理
                if self.db:
                    await self.db.upsert_vip_user(user_info)
                    
    async def _parse_member(self, payload):
        """解析用户进场 (欢迎来到直播间)"""
        try:
            message = douyin_pb2.MemberMessage()
            message.ParseFromString(payload)
            
            if message.HasField('user'):
                # ✅ 补上 self.live_id
                user_info = _extract_user_info(message.user, self.live_id)
                await self._check_and_save_vip(user_info)
                
        except Exception as e:
            pass # 进场消息非常多，普通用户的异常直接 pass 即可
    async def _parse_fansclub(self, payload):
        """解析粉丝团消息 (加入粉丝团、灯牌升级等)"""
        try:
            message = douyin_pb2.FansclubMessage()
            message.ParseFromString(payload)
            
            # ✅ 只要有 user 字段就提取，千万记得传 self.live_id 算出专属等级！
            if message.HasField('user'):
                user_info = _extract_user_info(message.user, self.live_id)
                await self._check_and_save_vip(user_info)
                
        except Exception as e:
            # 此类通知消息极多，常规异常直接 pass，防止日志刷屏
            pass 

    async def _parse_social(self, payload):
        """解析社交消息 (关注、分享直播间等)"""
        try:
            message = douyin_pb2.SocialMessage()
            message.ParseFromString(payload)
            
            # ✅ 同样提取 user 字段并传入 self.live_id
            if message.HasField('user'):
                user_info = _extract_user_info(message.user, self.live_id)
                await self._check_and_save_vip(user_info)
                
        except Exception as e:
            pass