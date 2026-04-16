from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime

# --- 1. 新功能模型 (收藏与检测) ---
class FavoriteStreamer(BaseModel):
    sec_uid: str
    nickname: str
    avatar_url: str
    group_name: str = "默认分组"
    display_id: Optional[str] = None     # 抖音号
    grade_icon_url: Optional[str] = None # 财富等级图标
    follower_count: int = 0              # 🔥 新增：粉丝数量
    created_at: datetime = Field(default_factory=datetime.now)

class BatchCheckRequest(BaseModel):
    user_sec_uid: str
    streamer_sec_uids: List[str]

# --- 2. 原有功能模型 (Legacy) ---
class Author(BaseModel):
    sec_uid: str
    nickname: str = "未知用户"
    weight: int = 3
    avatar: Optional[str] = None
    signature: Optional[str] = None
    live_status: int = 0
    web_rid: Optional[str] = None
    user_count: int = 0
    follower_count: int = 0
    class Config:
        populate_by_name = True

class RoomSchema(BaseModel):
    room_id: str
    title: str = ""
    nickname: Optional[str] = "" # 👈 新增这一行
    cover_url: Optional[str] = None
    created_at: Optional[datetime] = None
    end_time: Optional[datetime] = None
    max_viewers: int = 0
    like_count: int = 0
    live_status: int = 4
    total_diamond_count: int = 0
    
    class Config:
        populate_by_name = True

class PkBattle(BaseModel):
    battle_id: str
    room_id: str
    start_time: datetime
    mode: str
    teams: List[dict]
    created_at: datetime
    duration: Optional[int] = None

class QnAItem(BaseModel):
    id: Optional[str] = None 
    question: str
    answer: str
    order: int = 0 
    is_visible: bool = True 

class GlobalSearchResult(BaseModel):
    user_name: str
    sec_uid: str = ""
    avatar_url: str = ""
    content: str
    created_at: datetime
    room_id: str
    anchor_name: str = "未知主播"
    room_title: str = ""
    room_cover: str = ""
    pay_grade_icon: Optional[str] = ""
    fans_club_icon: Optional[str] = ""
    total_diamond_count: Optional[int] = 0 
    gift_icon: Optional[str] = ""
    # 👇 新增这一行
    gift_count: Optional[int] = 0
class DailyReportItem(BaseModel):
    date: str
    uid: str
    sec_uid: str
    nickname: str
    
    # 新增字段 (设置默认值防止旧数据报错)
    avatar_url: Optional[str] = "" 
    pay_grade_icon: Optional[str] = ""
    
    follower_count: int
    # club_name: str = "" # 前端不展示了，但后端可以保留或注释
    active_fans_count: int = 0  # 点亮中
    total_fans_club: int = 0    # 总量
    today_new_fans: int = 0     # 新加入
    task_1_completed: int = 0   # 送灯牌
    
    # 计算字段
    follower_diff: Optional[int] = 0

class DailyReportResponse(BaseModel):
    date: str
    items: List[DailyReportItem]
class CzLevelBatchRequest(BaseModel):
    targets: List[str]

class CzLevelResponse(BaseModel):
    query: Optional[str] = None      # 批量查询时带回原始查询词
    sec_uid: str
    display_id: str
    nickname: str
    avatar: str
    level: int
    source: str
    passed: bool
class SystemSettings(BaseModel):
    single_api_switch: int = 1
    batch_api_switch: int = 1
    enable_zero_level_shield: bool = True
    active_shield_days: int = 3
    single_api_query_limit: int = 600
    single_api_query_window: int = 3600
    single_global_api_query_limit: int = 20000
    batch_api_query_limit: int = 600
    batch_api_query_window: int = 3600
    batch_global_api_query_limit: int = 20000
