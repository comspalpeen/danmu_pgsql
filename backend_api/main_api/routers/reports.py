# 文件位置: api/routers/reports.py
from fastapi import APIRouter
from typing import List
from datetime import datetime, timedelta
from backend_api.common.database import get_db
from backend_api.common.models import DailyReportResponse, DailyReportItem
from backend_api.common.utils import build_avatar_url, build_grade_icon

router = APIRouter(tags=["reports"])

@router.get("/api/reports/daily", response_model=List[DailyReportResponse])
async def get_daily_reports(days: int = 7):
    pool = get_db()
    today = datetime.now().date()
    start_date = today - timedelta(days=days + 1)
    
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM daily_reports WHERE date >= $1 ORDER BY date DESC", start_date)
        
    grouped = {}
    lookup_map = {} 
    
    for row in rows:
        d = str(row["date"])
        uid = row["uid"]
        
        lookup_map[f"{uid}_{d}"] = row.get("follower_count", 0)
        if d not in grouped: grouped[d] = []
        
        item = DailyReportItem(
            date=d,
            uid=uid,
            sec_uid=row.get("sec_uid", ""),
            nickname=row.get("nickname", "未知"),
            avatar_url=build_avatar_url(row.get("avatar_url", "")),
            pay_grade_icon=build_grade_icon(row.get("pay_grade_icon", "")),
            follower_count=row.get("follower_count", 0),
            active_fans_count=row.get("active_fans_count", 0),
            total_fans_club=row.get("total_fans_club", 0),
            today_new_fans=row.get("today_new_fans", 0),
            task_1_completed=row.get("task_1_completed", 0)
        )
        grouped[d].append(item)

    result = []
    sorted_dates = sorted(grouped.keys(), reverse=True)
    display_dates = sorted_dates[:days]
    
    for date_str in display_dates:
        items = grouped[date_str]
        try:
            prev_date_str = str((datetime.strptime(date_str, "%Y-%m-%d").date() - timedelta(days=1)))
        except:
            prev_date_str = ""

        for item in items:
            prev_count = lookup_map.get(f"{item.uid}_{prev_date_str}")
            item.follower_diff = (item.follower_count - prev_count) if prev_count is not None else 0
        
        items.sort(key=lambda x: x.task_1_completed, reverse=True)
        result.append(DailyReportResponse(date=date_str, items=items))
        
    return result