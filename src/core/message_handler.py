# message_handler.py
import time
import logging
import orjson

from protobuf import douyin_pb2
from src.db.redis_client import get_redis

logger = logging.getLogger("MsgHandler")


def _get_safe_url(icon_obj):
    if not icon_obj:
        return ""
    try:
        if hasattr(icon_obj, "urlListList") and len(icon_obj.urlListList) > 0:
            return icon_obj.urlListList[0]
        if hasattr(icon_obj, "url_list_list") and len(icon_obj.url_list_list) > 0:
            return icon_obj.url_list_list[0]
    except Exception:
        pass
    return ""


def _extract_user_info(user, current_live_id=""):
    info = {
        "user_id": str(user.id),
        "user_name": user.nickName,
        "gender": user.gender,
        "sec_uid": user.secUid,
        "display_id": user.displayId,
        "avatar_url": _get_safe_url(user.AvatarThumb),
        "pay_grade": 0,
        "pay_grade_icon": "",
        "fans_club_level": 0,
        "fans_club_icon": "",
    }

    try:
        if user.HasField("PayGrade"):
            info["pay_grade"] = user.PayGrade.level
            info["pay_grade_icon"] = _get_safe_url(user.PayGrade.newImIconWithLevel)
    except Exception:
        pass

    try:
        if user.HasField("FansClub") and user.FansClub.HasField("data"):
            if 4 in user.FansClub.data.badge.icons:
                info["fans_club_icon"] = _get_safe_url(user.FansClub.data.badge.icons[4])
            info["fans_club_level"] = user.FansClub.data.level
    except Exception:
        pass

    try:
        for badge in user.NewBadgeImageList:
            if badge.imageType == 1:
                info["pay_grade"] = badge.content.level
                info["pay_grade_icon"] = _get_safe_url(badge)
            elif badge.imageType in (7, 51):
                if badge.content.level > 0:
                    info["fans_club_level"] = badge.content.level
                if not info["fans_club_icon"] or badge.imageType == 51:
                    info["fans_club_icon"] = _get_safe_url(badge)
    except Exception:
        pass

    info["cz_club_level"] = info.get("fans_club_level", 0) if str(current_live_id) == "615189692839" else 0
    return info


class MessageHandler:
    def __init__(self, live_id, room_id, db, gift_processor):
        self.live_id = live_id
        self.room_id = room_id
        self.db = db
        self.gift_processor = gift_processor

        self.last_seq_state = None
        self.last_seq_time = 0
        self.THROTTLE_INTERVAL = 1

        self.vip_users_cache = {}
        #self.current_guest_mic_users = set()

        # PK runtime state
        self.left_team_id = None
        self.right_team_id = None
        self.current_battle_id = None
    async def _reset_pk_state(self):
        """清理运行时的 PK 状态，并在 Redis 中销毁开始锁"""
        self.left_team_id = None
        self.right_team_id = None
        self.current_battle_id = None
        self.pk_start_info = None
        
        try:
            redis_client = get_redis()
            await redis_client.delete(f"pk:start:info:{self.room_id}")
            await redis_client.delete(f"pk:live:{self.room_id}")
        except Exception as e:
            logger.warning(f"[PK] 清除 Redis 状态失败: {e}")

    def _normalize_battle_id(self, battle_id, channel_id):
        battle_id = str(battle_id or "")
        channel_id = str(channel_id or "")
        return battle_id or channel_id

    def _order_two_teams(self, teams):
        if len(teams) != 2:
            return teams

        if self.left_team_id is None:
            self.left_team_id = teams[0]["team_id"]
            self.right_team_id = teams[1]["team_id"]
            # logger.info(
            #     f"[PK] 锁定左右阵营 room={self.room_id} left={self.left_team_id} right={self.right_team_id}"
            # )
            return teams

        team_map = {team["team_id"]: team for team in teams}
        left_team = team_map.get(self.left_team_id)
        right_team = team_map.get(self.right_team_id)
        if left_team and right_team:
            return [left_team, right_team]

        logger.warning(
            f"[PK] 阵营锁与当前包不一致，重新锁定 room={self.room_id} battle_id={self.current_battle_id}"
        )
        self.left_team_id = teams[0]["team_id"]
        self.right_team_id = teams[1]["team_id"]
        return teams

    async def handle(self, method, payload):
        if method in ("WebcastMemberMessage", "WebcastFansclubMessage", "WebcastSocialMessage"):
            if str(self.live_id) != "615189692839":
                return False
        try:
            if method == "WebcastChatMessage":
                await self._parse_chat(payload)
            elif method == "WebcastGiftMessage":
                await self._parse_gift(payload)
            elif method == "WebcastRoomUserSeqMessage":
                await self._parse_user_seq(payload)
            elif method == "WebcastLikeMessage":
                await self._parse_like(payload)
            elif method == "WebcastControlMessage":
                return await self._parse_control(payload)
            elif method == "WebcastScreenChatMessage":
                await self._parse_screen_chat(payload)
            elif method == "WebcastPrivilegeScreenChatMessage":
                await self._parse_privilege_screen_chat(payload)
            elif method == "WebcastMemberMessage":
                await self._parse_member(payload)
            elif method == "WebcastFansclubMessage":
                await self._parse_fansclub(payload)
            elif method == "WebcastSocialMessage":
                await self._parse_social(payload)
            # elif method == "WebcastLinkMessage":
            #      await self._parse_link_message(payload)
            elif method == "WebcastLinkMicMethod":
                await self._parse_pk_process(payload)
            elif method == "WebcastLinkMicBattleFinishMethod":
                await self._parse_pk_finish(payload)
            elif method == 'WebcastLinkMicBattleMethod':
                await self._parse_pk_start(payload)  
        except Exception as e:
            logger.error(f"消息分发解析异常 [{method}]: {e}", exc_info=True)
        return False

    async def _parse_control(self, payload):
        try:
            message = douyin_pb2.ControlMessage()
            message.ParseFromString(payload)
            if message.status == 3:
                logger.info(f"[Control] 收到下播信号 room={self.room_id}")
                if self.db and self.room_id:
                    await self.db.set_room_ended(self.room_id)
                return True
        except Exception as e:
            logger.error(f"解析 Control 异常: {e}", exc_info=True)
        return False

    async def _parse_chat(self, payload):
        try:
            message = douyin_pb2.ChatMessage()
            message.ParseFromString(payload)

            user_info = _extract_user_info(message.user, self.live_id)
            event_ts = message.eventTime
            event_time_val = event_ts if event_ts > 0 else time.time()

            chat_data = {
                "web_rid": self.live_id,
                "room_id": self.room_id,
                "content": message.content,
                "event_time": event_time_val,
                "created_at": time.time(),
            }
            chat_data.update(user_info)

            if self.db:
                await self.db.insert_chat(chat_data)
        except Exception as e:
            logger.error(f"解析弹幕异常: {e}", exc_info=True)

    async def _parse_gift(self, payload):
        try:
            message = douyin_pb2.GiftMessage()
            message.ParseFromString(payload)
            gift = message.gift

            user_info = _extract_user_info(message.user, self.live_id)

            repeat_count = message.repeatCount
            combo_count = message.comboCount
            group_count = message.groupCount
            diamond_count = gift.diamondCount
            if repeat_count > 0:
                combo_count = repeat_count
                group_count = 1

            send_time_ms = message.sendTime if message.sendTime > 0 else int(time.time() * 1000)
            gift_data = {
                "web_rid": self.live_id,
                "room_id": self.room_id,
                "gift_icon_url": _get_safe_url(gift.icon),
                "gift_id": str(gift.id),
                "gift_name": gift.name,
                "diamond_count": diamond_count,
                "combo_count": combo_count,
                "group_count": group_count,
                "repeat_count": repeat_count,
                "group_id": str(message.groupId),
                "repeat_end": message.repeatEnd,
                "trace_id": message.traceId,
                "send_time": send_time_ms / 1000.0,
                "created_at": time.time(),
            }
            gift_data.update(user_info)

            if self.gift_processor:
                await self.gift_processor.process_gift(gift_data)
        except Exception as e:
            logger.error(f"解析礼物异常: {e}", exc_info=True)

    async def _parse_screen_chat(self, payload):
        try:
            msg = douyin_pb2.ScreenChatMessage()
            msg.ParseFromString(payload)
            if not msg.HasField("user") or not msg.content:
                return

            user_info = _extract_user_info(msg.user, self.live_id)
            chat_data = {
                "web_rid": self.live_id,
                "room_id": str(self.room_id),
                "content": f"[房管飘屏] {msg.content}",
                "event_time": time.time(),
                "created_at": time.time(),
            }
            chat_data.update(user_info)

            if self.db:
                await self.db.insert_chat(chat_data)
        except Exception as e:
            logger.error(f"解析房管飘屏异常: {e}", exc_info=True)

    async def _parse_privilege_screen_chat(self, payload):
        try:
            msg = douyin_pb2.WebcastPrivilegeScreenChatMessage()
            msg.ParseFromString(payload)
            if not msg.HasField("user") or not msg.content:
                return

            user_info = _extract_user_info(msg.user, self.live_id)
            chat_data = {
                "web_rid": self.live_id,
                "room_id": str(self.room_id),
                "content": f"[特权飘屏] {msg.content}",
                "event_time": time.time(),
                "created_at": time.time(),
            }
            chat_data.update(user_info)

            if self.db:
                await self.db.insert_chat(chat_data)
        except Exception as e:
            logger.error(f"解析特权飘屏异常: {e}", exc_info=True)

    async def _parse_user_seq(self, payload):
        now = time.time()
        if now - self.last_seq_time < self.THROTTLE_INTERVAL:
            return

        time_diff = now - self.last_seq_time if self.last_seq_time > 0 else 0
        self.last_seq_time = now

        try:
            message = douyin_pb2.RoomUserSeqMessage()
            message.ParseFromString(payload)
            stats = {"user_count": message.total, "total_user": message.totalUser}
            inc_data = {}
            if self.last_seq_state:
                inc_data = {"total_watch_time_sec": message.total * time_diff}
            self.last_seq_state = {"online": message.total, "total": message.totalUser, "time": now}

            if self.db and self.room_id:
                await self.db.update_room_stats(self.room_id, stats)
                if inc_data:
                    await self.db.increment_room_stats(self.room_id, inc_data)
        except Exception as e:
            logger.error(f"解析 UserSeq 异常: {e}", exc_info=True)

    async def _parse_like(self, payload):
        try:
            message = douyin_pb2.LikeMessage()
            message.ParseFromString(payload)

            if message.HasField("user"):
                user_info = _extract_user_info(message.user, self.live_id)
                await self._check_and_save_vip(user_info)

            if self.db and self.room_id:
                await self.db.update_room_stats(self.room_id, {"like_count": message.total})
        except Exception as e:
            logger.error(f"解析点赞异常: {e}", exc_info=True)

    async def _parse_pk_process(self, payload):
        """解析过程包：验证锁、算分、合并资料后广播"""
        try:
            message = douyin_pb2.LinkMicMethod()
            message.ParseFromString(payload)
            if not message.user_scores:
                return

            battle_id = self._normalize_battle_id(
                getattr(message, "battle_id", 0),
                getattr(message, "channel_id", 0),
            )
            channel_id = str(getattr(message, "channel_id", 0) or "")
            if not battle_id:
                return

            # ==========================================
            # 🔥 拦截器：从 Redis 检查是否有开始锁
            # ==========================================
            redis_client = get_redis()
            raw_start_info = await redis_client.get(f"pk:start:info:{self.room_id}")
            
            if not raw_start_info:
                # 没拿到开始包，或者 PK 已正常结束导致锁被删，直接丢弃过程包
                return
            
            # 把 Redis 里的状态赋给 self，供后面的 _broadcast_snapshot 下发给前端
            self.pk_start_info = orjson.loads(raw_start_info)

            if self.current_battle_id != battle_id:
                self.current_battle_id = battle_id

            team_map = {}
            team_order = []

            for s in message.user_scores:
                uid = str(s.user_id)
                team_rank = int(getattr(s, "multi_pk_team_rank", 0) or 0)
                team_id = str(team_rank) if team_rank > 0 else uid
                member_score = int(getattr(s, "score", 0) or 0)
                team_score_from_msg = int(getattr(s, "multi_pk_team_score", 0) or 0)

                if team_id not in team_map:
                    team_map[team_id] = {
                        "team_id": team_id,
                        "team_score": 0, 
                        "anchors": [],
                    }
                    team_order.append(team_id)

                if team_rank > 0:
                    team_map[team_id]["team_score"] = max(team_map[team_id]["team_score"], team_score_from_msg)
                else:
                    team_map[team_id]["team_score"] += member_score

                # ==========================================
                # 🔥 资料读取：从 Redis 拿取高清头像和真实昵称
                # ==========================================
                raw_cached = await redis_client.hget("pk:anchor:cache", uid)
                if raw_cached:
                    cached_info = orjson.loads(raw_cached)
                    nickname = cached_info.get("nickname")
                    avatar = cached_info.get("avatar")
                else:
                    nickname = f"用户_{uid[-4:]}"
                    avatar = ""

                team_map[team_id]["anchors"].append({
                    "user_id": uid,
                    "nickname": nickname,
                    "avatar": avatar,
                    "score": member_score
                })

            teams = [team_map[tid] for tid in team_order]
            teams = self._order_two_teams(teams)

            await self._broadcast_snapshot(battle_id, channel_id, teams)
        except Exception as e:
            logger.error(f"❌ [PK 解析错误] 过程包异常: {e}", exc_info=True)

    async def _parse_pk_finish(self, payload):
        try:
            message = douyin_pb2.LinkMicBattleFinishMethod()
            message.ParseFromString(payload)

            # 1. 清理运行时的 PK 状态
            await self._reset_pk_state()

            try:
                # 修改：同步修改需要删除的 Key 名称
                await get_redis().delete(f"pk:live:{self.room_id}")
            except Exception as redis_e:
                logger.warning(f"[PK] 清理 Redis 实时状态失败 room={self.room_id}: {redis_e}")

            status = int(getattr(message.info, "status", 0) or 0)
            if status != 2:
                return

            battle_id = str(getattr(message.info, "battle_id", 0) or "")
            channel_id = str(getattr(message.info, "channel_id", 0) or "")
            duration = int(getattr(message.info, "duration", 0) or 0)
            start_time_ms = int(getattr(message.info, "start_time_ms", 0) or 0)
            start_time_val = start_time_ms / 1000.0 if start_time_ms > 0 else time.time()

            scores_map = {}
            has_valid_win_status = False
            
            # 2. 提取分数，并全局探测是否存在真实的 win_status (用于区分个人战和团队/1v1战)
            for score_item in message.scores:
                uid = str(score_item.user_id)
                win_status = int(getattr(score_item, "win_status", 0) or 0)
                
                if win_status in [1, 2]: 
                    has_valid_win_status = True
                    
                scores_map[uid] = {
                    "score": int(getattr(score_item, "score", 0) or 0),
                    "rank": int(getattr(score_item, "rank", 0) or 0),
                    "win_status": win_status,
                }

            # 3. 提取贡献榜 (榜一大哥)
            contrib_map = {}
            for c_group in message.contributors:
                anchor_id = str(c_group.anchor_id_str or c_group.anchor_id)
                top_list = []
                for item in c_group.list[:3]:
                    top_list.append({
                        "user_id": str(item.id),
                        "nickname": item.nickname,
                        "avatar": _get_safe_url(item.avatar),
                        "score": int(getattr(item, "score", 0) or 0),
                        "rank": int(getattr(item, "rank", 0) or 0),
                    })
                contrib_map[anchor_id] = top_list

            total_anchors = sum(len(army.list) for army in message.anchors)

            # 4. 判定模式
            mode_type = "team_battle" if (has_valid_win_status or total_anchors == 2) else "free_for_all"

            # 5. 核心队伍划分逻辑 (回归经过业务验证的策略)
            teams_map = {}
            for army in message.anchors:
                for anchor_item in army.list:
                    # Proto3 安全读取判断
                    try:
                        if not anchor_item.HasField('user'): continue
                        uid = str(anchor_item.user.id)
                        if not uid or uid == "0": continue
                    except Exception:
                        continue

                    score_info = scores_map.get(uid, {})
                    
                    anchor_data = {
                        "user_id": uid,
                        "nickname": anchor_item.user.nickname,
                        "avatar": _get_safe_url(anchor_item.user.avatar_thumb),
                        "score": score_info.get("score", 0),
                        "rank": score_info.get("rank", 0),
                        "contributors": contrib_map.get(uid, [])
                    }

                    # 🌟 恢复你的高光判定：有 win_status 按胜负分阵营，没有则各自为营(uid)
                    team_id = str(score_info.get("win_status", 0)) if has_valid_win_status else uid

                    if team_id not in teams_map:
                        teams_map[team_id] = {
                            "team_id": team_id, 
                            "win_status": score_info.get("win_status", 0), 
                            "anchors": []
                        }
                    
                    teams_map[team_id]["anchors"].append(anchor_data)

            final_teams = list(teams_map.values())
            
            # 如果是个人战，按照排名对生成的各个“单人队伍”进行排序
            if mode_type == "free_for_all":
                final_teams.sort(key=lambda t: t["anchors"][0]["rank"] if t["anchors"] else 999)

            pk_result = {
                "battle_id": battle_id,
                "room_id": self.room_id,
                "channel_id": channel_id,
                "start_time": start_time_val,
                "duration": duration,
                "mode": mode_type,
                "status": status,
                "created_at": time.time(),
                "teams": final_teams,
            }

            if self.db:
                await self.db.save_pk_result(pk_result)

            # ==========================================
            # 🌟 新增：发送 SSE 谢幕包
            # ==========================================
            try:
                final_snapshot = {
                    "battle_id": battle_id,
                    "channel_id": channel_id,
                    "room_id": str(self.room_id),
                    "mode": mode_type,
                    "status": 2, # 明确告知前端已结束
                    "teams": final_teams,
                    "start_info": getattr(self, "pk_start_info", None), 
                    "updated_at": int(time.time() * 1000),
                }
                redis_client = get_redis()
                # 只推送到 pub/sub 触发 SSE，不保留在 redis key 中
                await redis_client.publish("pk:live:updates", orjson.dumps(final_snapshot).decode("utf-8"))
            except Exception as broadcast_e:
                logger.error(f"发送 PK 结束谢幕包失败: {broadcast_e}")

            # 清理运行时状态（保持原有逻辑）
            await self._reset_pk_state()
            try:
                await get_redis().delete(f"pk:live:{self.room_id}")
            except Exception as redis_e:
                pass

            #logger.info(f"[PK] 正式结算入库 room={self.room_id} battle_id={battle_id} mode={mode_type} teams={len(final_teams)}")
        except Exception as e:
            logger.error(f"解析 PK 结算包异常: {e}", exc_info=True)
    async def _check_and_save_vip(self, user_info):
        if str(self.live_id) != "615189692839":
            return
        fans_level = user_info.get("fans_club_level", 0)
        if fans_level >= 10:
            uid = user_info.get("user_id")
            now = time.time()
            last_record_time = self.vip_users_cache.get(uid, 0)
            if now - last_record_time > 300:
                self.vip_users_cache[uid] = now
                if self.db:
                    await self.db.upsert_vip_user(user_info, self.live_id)

    async def _parse_member(self, payload):
        try:
            message = douyin_pb2.MemberMessage()
            message.ParseFromString(payload)
            if message.HasField("user"):
                user_info = _extract_user_info(message.user, self.live_id)
                await self._check_and_save_vip(user_info)
        except Exception:
            pass

    async def _parse_fansclub(self, payload):
        try:
            message = douyin_pb2.FansclubMessage()
            message.ParseFromString(payload)
            if message.HasField("user"):
                user_info = _extract_user_info(message.user, self.live_id)
                await self._check_and_save_vip(user_info)
        except Exception:
            pass

    async def _parse_social(self, payload):
        try:
            message = douyin_pb2.SocialMessage()
            message.ParseFromString(payload)
            if message.HasField("user"):
                user_info = _extract_user_info(message.user, self.live_id)
                await self._check_and_save_vip(user_info)
        except Exception:
            pass

    # async def _parse_link_message(self, payload):
    #     try:
    #         message = douyin_pb2.LinkMessage()
    #         message.ParseFromString(payload)
    #         if message.scene != 8:
    #             return

    #         has_change = message.HasField("linked_list_change_content")
    #         has_update = message.HasField("update_user_content")

    #         target_user_id = 63871524957
    #         target_own_room = "615189692839"

    #         if has_change or has_update:
    #             linked_users = []
    #             if has_change:
    #                 linked_users = message.linked_list_change_content.linked_users
    #             elif has_update:
    #                 linked_users = message.update_user_content.linked_users

    #             current_packet_user_ids = set()
    #             for lu in linked_users:
    #                 if lu.HasField("user"):
    #                     if str(self.live_id) == target_own_room and lu.user.id == target_user_id:
    #                         continue
    #                     current_packet_user_ids.add(lu.user.id)

    #             if target_user_id in current_packet_user_ids and target_user_id not in self.current_guest_mic_users:
    #                 logger.info(f"[Link] 目标刚上麦 room={self.live_id}")
    #             elif target_user_id not in current_packet_user_ids and target_user_id in self.current_guest_mic_users:
    #                 logger.info(f"[Link] 目标已下麦 room={self.live_id}")

    #             self.current_guest_mic_users = current_packet_user_ids
    #     except Exception as e:
    #         logger.error(f"_parse_link_message 解析异常: {e}", exc_info=True)
    async def _parse_pk_start(self, payload):
        """解析开始包：写入倒计时锁和主播资料到 Redis"""
        try:
            message = douyin_pb2.LinkMicBattle()
            message.ParseFromString(payload)
            info = message.info
            redis_client = get_redis()
            
            # 1. 提取并持久化倒计时/开始状态到 Redis
            start_data = {
                "start_time_ms": info.start_time_ms,
                "duration": info.duration,
                "battle_id": str(info.battle_id)
            }
            state_key = f"pk:start:info:{self.room_id}"
            # 加上 60 秒的缓冲期，防止稍微超时就被自动清理
            await redis_client.set(state_key, orjson.dumps(start_data), ex=info.duration + 60)

            # 2. 提取并持久化主播资料到 Redis 全局 Hash
            anchor_data = {}
            for army in message.anchors:
                for anchor_item in army.list:
                    if anchor_item.HasField('user'):
                        uid = str(anchor_item.user.id)
                        data = {
                            "nickname": anchor_item.user.nickname,
                            "avatar": _get_safe_url(anchor_item.user.avatar_thumb)
                        }
                        # orjson.dumps 出来是 bytes，解码为 str 存入 Hash
                        anchor_data[uid] = orjson.dumps(data).decode('utf-8')

            if anchor_data:
                await redis_client.hset("pk:anchor:cache", mapping=anchor_data)
                await redis_client.expire("pk:anchor:cache", 86400) # 主播资料保留 24 小时

            #logger.info(f"[PK] 激活开始锁并持久化至 Redis: {start_data}")

            # 3. 广播初始空包 (携带 channel_id 给前端开辟空间)
            channel_id = str(getattr(message, "channel_id", getattr(info, "channel_id", "")))
            self.pk_start_info = start_data  # 临时赋值给 self 供紧接着的广播使用
            await self._broadcast_snapshot(info.battle_id, channel_id, [])

        except Exception as e:
            logger.error(f"解析开始包异常: {e}", exc_info=True)
    async def _broadcast_snapshot(self, battle_id, channel_id, teams):
        """统一封装打包发给 Redis 发布订阅流"""
        try:
            mode_type = "free_for_all" if len(teams) > 2 else "team_battle"


            left_score = next((t["team_score"] for t in teams if t["team_id"] == self.left_team_id), 0) if self.left_team_id else 0
            right_score = next((t["team_score"] for t in teams if t["team_id"] == self.right_team_id), 0) if self.right_team_id else 0

            snapshot = {
                "battle_id": str(battle_id),
                "channel_id": str(channel_id),
                "room_id": str(self.room_id),
                "mode": mode_type,
                "start_info": getattr(self, "pk_start_info", None), 
                "left_team_id": self.left_team_id,
                "right_team_id": self.right_team_id,
                "left_team_score": left_score,
                "right_team_score": right_score,
                "teams": teams,
                "status": 1,
                "updated_at": int(time.time() * 1000),
            }

            redis_client = get_redis()
            payload_str = orjson.dumps(snapshot).decode("utf-8")
            
            # SSE 状态快照，过期时间设为 5 分钟
            await redis_client.set(f"pk:live:{self.room_id}", payload_str, ex=300)
            # 触发 SSE 实时推送
            await redis_client.publish("pk:live:updates", payload_str)
            
        except Exception as e:
            logger.error(f"❌ [PK 广播错误]: {e}", exc_info=True)