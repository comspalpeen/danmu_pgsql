from collections import OrderedDict
from datetime import datetime
from html import escape
from typing import Dict, List, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from backend_api.common.database import get_db
from backend_api.common.models import (
    GiftReportPreviewRequest,
    GiftReportPreviewResponse,
    GiftReportRow,
    SpenderThresholdPreviewRequest,
    SpenderThresholdPreviewResponse,
    SpenderThresholdRow,
    ToolsPreviewMeta,
)

router = APIRouter(tags=["tools"])


def _parse_datetime(value: str) -> datetime:
    if not value:
        raise HTTPException(status_code=400, detail="时间参数不能为空")

    normalized = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="时间格式非法") from exc

    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def _clean_keywords(keywords: List[str]) -> List[str]:
    seen = OrderedDict()
    for keyword in keywords or []:
        text = str(keyword or "").strip()
        if text:
            seen[text] = None
    return list(seen.keys())


def _profile_url(sec_uid: str) -> str:
    return f"https://www.douyin.com/user/{sec_uid}" if sec_uid else ""


def _format_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_short_time(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S")


def _build_meta(room_row, start_time: datetime, end_time: datetime) -> ToolsPreviewMeta:
    return ToolsPreviewMeta(
        sec_uid=room_row.get("sec_uid") or "",
        room_id=room_row.get("room_id") or "",
        anchor_name=room_row.get("nickname") or "未知主播",
        room_title=room_row.get("title") or "",
        start_time=_format_time(start_time),
        end_time=_format_time(end_time),
    )


async def _get_room_context(sec_uid: str, room_id: str) -> Dict:
    pool = get_db()
    async with pool.acquire() as conn:
        room_row = await conn.fetchrow(
            """
            SELECT room_id, user_id, sec_uid, nickname, title, created_at, end_time
            FROM rooms
            WHERE room_id = $1
            """,
            room_id,
        )
        if not room_row:
            raise HTTPException(status_code=404, detail="场次不存在")

        requested_user = await conn.fetchrow(
            "SELECT user_id, sec_uid FROM users WHERE sec_uid = $1 LIMIT 1",
            sec_uid,
        )

    room = dict(room_row)
    if requested_user and room.get("user_id"):
        if room["user_id"] != requested_user["user_id"]:
            raise HTTPException(status_code=400, detail="所选场次不属于该主播")
    elif room.get("sec_uid") and room["sec_uid"] != sec_uid:
        raise HTTPException(status_code=400, detail="所选场次不属于该主播")

    room["sec_uid"] = sec_uid
    return room


async def _fetch_gift_rows(room_id: str, start_time: datetime, end_time: datetime, gift_keywords: List[str] | None = None) -> List[Dict]:
    pool = get_db()
    conditions = [
        "g.room_id = $1",
        "g.send_time IS NOT NULL",
        "g.send_time >= $2",
        "g.send_time <= $3",
    ]
    args: List = [room_id, start_time, end_time]
    idx = 4

    if gift_keywords:
        keyword_conditions = []
        for keyword in gift_keywords:
            keyword_conditions.append(f"g.gift_name ILIKE ${idx}")
            args.append(f"%{keyword}%")
            idx += 1
        conditions.append("(" + " OR ".join(keyword_conditions) + ")")

    sql = f"""
        SELECT
            g.user_id,
            COALESCE(u.user_name, g.user_name) AS user_name,
            COALESCE(u.display_id, '') AS display_id,
            COALESCE(u.sec_uid, '') AS sec_uid,
            COALESCE(g.gift_name, '') AS gift_name,
            COALESCE(g.diamond_count, 0) AS diamond_count,
            COALESCE(g.combo_count, 1) AS combo_count,
            COALESCE(g.group_count, 1) AS group_count,
            COALESCE(g.total_diamond_count, 0) AS total_diamond_count,
            g.send_time
        FROM live_gifts g
        LEFT JOIN users u ON g.user_id = u.user_id
        WHERE {" AND ".join(conditions)}
        ORDER BY g.send_time ASC, g.id ASC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [dict(row) for row in rows]


def _format_gift_counts(gift_counts: Dict[str, int]) -> List[str]:
    sorted_items = sorted(
        gift_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )
    return [f"{name} × {count}" for name, count in sorted_items]


def _build_gift_preview_rows(rows: List[Dict]) -> List[GiftReportRow]:
    grouped: Dict[Tuple[str, str, str], Dict] = OrderedDict()

    for row in rows:
        key = (
            row.get("user_id") or "",
            row.get("sec_uid") or "",
            row.get("display_id") or "",
            row.get("user_name") or "",
        )
        if key not in grouped:
            grouped[key] = {
                "user_name": row.get("user_name") or "神秘人",
                "display_id": row.get("display_id") or "",
                "sec_uid": row.get("sec_uid") or "",
                "profile_url": _profile_url(row.get("sec_uid") or ""),
                "total_count": 0,
                "send_times": [],
                "gift_counts": {},
                "first_time": row.get("send_time"),
            }

        item = grouped[key]
        current_count = max(0, int(row.get("combo_count") or 0)) * max(0, int(row.get("group_count") or 0))
        item["total_count"] += current_count
        send_time = row.get("send_time")
        if send_time:
            item["send_times"].append(_format_short_time(send_time))
        gift_name = row.get("gift_name") or ""
        if gift_name:
            item["gift_counts"][gift_name] = item["gift_counts"].get(gift_name, 0) + current_count

    sorted_items = sorted(
        grouped.values(),
        key=lambda item: (-item["total_count"], item["first_time"] or datetime.max),
    )

    result = []
    for index, item in enumerate(sorted_items, start=1):
        result.append(
            GiftReportRow(
                rank=index,
                user_name=item["user_name"],
                display_id=item["display_id"],
                sec_uid=item["sec_uid"],
                profile_url=item["profile_url"],
                total_count=item["total_count"],
                send_times=item["send_times"],
                gift_list=_format_gift_counts(item["gift_counts"]),
            )
        )
    return result


def _build_spender_preview_rows(rows: List[Dict], min_total_diamond: int) -> List[SpenderThresholdRow]:
    grouped: Dict[Tuple[str, str, str], Dict] = OrderedDict()

    for row in rows:
        key = (
            row.get("user_id") or "",
            row.get("sec_uid") or "",
            row.get("display_id") or "",
            row.get("user_name") or "",
        )
        if key not in grouped:
            grouped[key] = {
                "user_name": row.get("user_name") or "神秘人",
                "display_id": row.get("display_id") or "",
                "sec_uid": row.get("sec_uid") or "",
                "profile_url": _profile_url(row.get("sec_uid") or ""),
                "total_diamond_count": 0,
                "gift_counts": {},
                "first_time": row.get("send_time"),
            }

        item = grouped[key]
        item["total_diamond_count"] += int(row.get("total_diamond_count") or 0)
        gift_name = row.get("gift_name") or ""
        if gift_name:
            current_count = max(0, int(row.get("combo_count") or 0)) * max(0, int(row.get("group_count") or 0))
            item["gift_counts"][gift_name] = item["gift_counts"].get(gift_name, 0) + current_count

    filtered_items = [
        item for item in grouped.values() if item["total_diamond_count"] >= min_total_diamond
    ]
    sorted_items = sorted(
        filtered_items,
        key=lambda item: (-item["total_diamond_count"], item["user_name"]),
    )

    result = []
    for index, item in enumerate(sorted_items, start=1):
        result.append(
            SpenderThresholdRow(
                rank=index,
                user_name=item["user_name"],
                display_id=item["display_id"],
                sec_uid=item["sec_uid"],
                profile_url=item["profile_url"],
                total_diamond_count=item["total_diamond_count"],
                gift_list=_format_gift_counts(item["gift_counts"]),
            )
        )
    return result


def _render_html(meta: ToolsPreviewMeta, summary_lines: List[str], headers: List[str], body_rows: List[List[str]], empty_text: str) -> str:
    summary_html = "".join(
        f'<span class="chip">{escape(line)}</span>' for line in summary_lines if line
    )

    if body_rows:
        header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
        row_html = ""
        for row in body_rows:
            row_html += "<tr>" + "".join(
                f'<td><div class="cell">{cell}</div></td>' for cell in row
            ) + "</tr>"
        table_html = f"""
        <div class="table-shell">
          <table>
            <thead>
              <tr>{header_html}</tr>
            </thead>
            <tbody>{row_html}</tbody>
          </table>
        </div>
        """
    else:
        table_html = f'<div class="empty">{escape(empty_text)}</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{escape(meta.anchor_name)} - 礼物报表</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #eef3f8;
      --panel: rgba(255, 255, 255, 0.9);
      --ink: #18222d;
      --muted: #687587;
      --line: #d6dde7;
      --accent: #123955;
      --accent-soft: #e8eef6;
      --shadow: 0 24px 60px rgba(18, 33, 50, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top, rgba(18, 57, 85, 0.12), transparent 28%),
        linear-gradient(180deg, #f7fafc 0%, var(--bg) 100%);
      padding: 24px 14px 40px;
    }}
    .page {{
      max-width: 860px;
      margin: 0 auto;
    }}
    .shell {{
      background: var(--panel);
      border: 1px solid rgba(255, 255, 255, 0.7);
      border-radius: 28px;
      box-shadow: var(--shadow);
      overflow: hidden;
      backdrop-filter: blur(18px);
    }}
    .hero {{
      padding: 28px 24px 20px;
      background: linear-gradient(135deg, rgba(18, 57, 85, 0.98), rgba(28, 83, 118, 0.88));
      color: #f7fbff;
    }}
    .eyebrow {{
      font-size: 12px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      opacity: 0.72;
      margin-bottom: 12px;
    }}
    h1 {{
      font-size: 26px;
      line-height: 1.2;
      margin: 0 0 8px;
    }}
    .sub {{
      margin: 0;
      color: rgba(247, 251, 255, 0.82);
      font-size: 14px;
      line-height: 1.7;
    }}
    .content {{
      padding: 22px 18px 24px;
    }}
    .summary {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }}
    .chip {{
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid rgba(18, 57, 85, 0.08);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
      line-height: 1.4;
    }}
    .table-shell {{
      border: 1px solid var(--line);
      border-radius: 20px;
      overflow: hidden;
      background: white;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    
    th:nth-child(1), td:nth-child(1) {{ width: 10%; text-align: center; }} 
    th:nth-child(2), td:nth-child(2) {{ width: 22%; }} 
    th:nth-child(3), td:nth-child(3) {{ width: 12%; text-align: center; }} 
    th:nth-child(4), td:nth-child(4) {{ width: 34%; }} /* 给礼物详情最大空间 */
    th:nth-child(5), td:nth-child(5) {{ width: 22%; }} /* 赠送时间/总消费稍微收缩 */

    th, td {{
      padding: 8px 4px; 
      font-size: 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
      /* 把之前的 break-all 换成 break-word，让文本换行更自然 */
      word-break: break-word; 
      line-height: 1.5;
    }}
    th {{
      background: #f7f9fc;
      color: var(--accent);
      font-weight: bold;
    }}
    tbody tr:nth-child(even) {{
      background: rgba(248, 250, 252, 0.8);
    }}
    tbody tr:last-child td {{
      border-bottom: none;
    }}
    .cell {{
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .link {{
      display: inline-block;
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
      border: 1px solid var(--accent);
      padding: 2px 10px;
      border-radius: 20px; /* 胶囊圆角 */
      background: var(--accent-soft);
      font-size: 11px;
      white-space: nowrap;
      transition: all 0.2s ease;
      line-height: 1.4;
    }}
    
    /* 增加悬停效果，让交互感更强 */
    .link:hover {{
      background: var(--accent);
      color: #ffffff;
      box-shadow: 0 2px 8px rgba(18, 57, 85, 0.2);
    }}
    .muted {{
      color: var(--muted);
    }}
    .empty {{
      border: 1px dashed var(--line);
      background: rgba(255, 255, 255, 0.72);
      border-radius: 20px;
      padding: 48px 18px;
      text-align: center;
      color: var(--muted);
      font-size: 14px;
    }}
    @media (min-width: 920px) {{
      body {{
        padding: 48px 18px 64px;
      }}
      .page {{
        max-width: 980px;
      }}
      .shell {{
        padding: 14px;
        background: linear-gradient(180deg, rgba(255,255,255,0.88), rgba(244,247,251,0.94));
      }}
      .hero, .content {{
        border-radius: 22px;
      }}
      .hero {{
        margin-bottom: 14px;
      }}
      th, td {{
        padding: 14px 12px;
        font-size: 13px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="shell">
      <section class="hero">
        <div class="eyebrow">Gift Export</div>
        <h1>{escape(meta.anchor_name)}</h1>
        <p class="sub">{escape(meta.room_title or "未命名场次")}<br />{escape(meta.start_time)} 至 {escape(meta.end_time)}</p>
      </section>
      <section class="content">
        <div class="summary">{summary_html}</div>
        {table_html}
      </section>
    </div>
  </div>
</body>
</html>"""


def _gift_rows_to_html(rows: List[GiftReportRow]) -> List[List[str]]:
    body_rows = []
    for row in rows:
        profile = (
            f'<a class="link" href="{escape(row.profile_url)}" target="_blank" rel="noopener noreferrer">主页</a>'
            if row.profile_url
            else '<span class="muted">无</span>'
        )
        # 用 <br> 拼接，实现完美的垂直独立换行
        gifts_html = "<br>".join(escape(g) for g in row.gift_list) if row.gift_list else "-"
        times_html = "<br>".join(escape(t) for t in row.send_times) if row.send_times else "-"
        
        body_rows.append(
            [
                escape(str(row.rank)),
                escape(row.user_name),
                profile,
                gifts_html,  # 第 4 列：礼物详情
                times_html,  # 第 5 列：赠送时间
            ]
        )
    return body_rows


def _spender_rows_to_html(rows: List[SpenderThresholdRow]) -> List[List[str]]:
    body_rows = []
    for row in rows:
        profile = (
            f'<a class="link" href="{escape(row.profile_url)}" target="_blank" rel="noopener noreferrer">主页</a>'
            if row.profile_url
            else '<span class="muted">无</span>'
        )
        # 同样用 <br> 拼接礼物列表
        gifts_html = "<br>".join(escape(g) for g in row.gift_list) if row.gift_list else "-"
        
        body_rows.append(
            [
                escape(str(row.rank)),
                escape(row.user_name),
                profile,
                gifts_html,                         # 第 4 列：礼物详情
                escape(str(row.total_diamond_count)), # 第 5 列：总消费
            ]
        )
    return body_rows


@router.post("/api/tools/gift-report/preview", response_model=GiftReportPreviewResponse)
async def preview_gift_report(payload: GiftReportPreviewRequest):
    start_time = _parse_datetime(payload.start_time)
    end_time = _parse_datetime(payload.end_time)
    if start_time > end_time:
        raise HTTPException(status_code=400, detail="开始时间不能晚于结束时间")

    gift_keywords = _clean_keywords(payload.gift_keywords)
    if not gift_keywords:
        raise HTTPException(status_code=400, detail="请至少输入一个礼物关键词")

    room = await _get_room_context(payload.sec_uid, payload.room_id)
    rows = await _fetch_gift_rows(payload.room_id, start_time, end_time, gift_keywords)
    preview_rows = _build_gift_preview_rows(rows)

    return GiftReportPreviewResponse(
        meta=_build_meta(room, start_time, end_time),
        gift_keywords=gift_keywords,
        rows=preview_rows,
    )


@router.post("/api/tools/gift-report/export")
async def export_gift_report(payload: GiftReportPreviewRequest):
    preview = await preview_gift_report(payload)
    html = _render_html(
        preview.meta,
        [
            "导出类型：礼物名单",
            f"礼物关键词：{'；'.join(preview.gift_keywords)}",
            f"结果数量：{len(preview.rows)} 人",
        ],
        ["序号", "昵称", "主页", "礼物详情", "赠送时间"],
        _gift_rows_to_html(preview.rows),
        "该时间段内未查询到符合条件的礼物数据。",
    )
    filename = f"gift_report_{preview.meta.room_id}.html"
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/tools/spender-threshold/preview", response_model=SpenderThresholdPreviewResponse)
async def preview_spender_threshold(payload: SpenderThresholdPreviewRequest):
    start_time = _parse_datetime(payload.start_time)
    end_time = _parse_datetime(payload.end_time)
    if start_time > end_time:
        raise HTTPException(status_code=400, detail="开始时间不能晚于结束时间")
    if payload.min_total_diamond < 0:
        raise HTTPException(status_code=400, detail="消费阈值不能小于 0")

    room = await _get_room_context(payload.sec_uid, payload.room_id)
    rows = await _fetch_gift_rows(payload.room_id, start_time, end_time)
    preview_rows = _build_spender_preview_rows(rows, payload.min_total_diamond)

    return SpenderThresholdPreviewResponse(
        meta=_build_meta(room, start_time, end_time),
        min_total_diamond=payload.min_total_diamond,
        rows=preview_rows,
    )


@router.post("/api/tools/spender-threshold/export")
async def export_spender_threshold(payload: SpenderThresholdPreviewRequest):
    preview = await preview_spender_threshold(payload)
    html = _render_html(
        preview.meta,
        [
            "导出类型：消费阈值名单",
            f"消费阈值：{preview.min_total_diamond} 钻石",
            f"结果数量：{len(preview.rows)} 人",
        ],
        ["序号", "昵称", "主页", "礼物详情", "总钻石"],
        _spender_rows_to_html(preview.rows),
        "该时间段内没有达到消费阈值的用户。",
    )
    filename = f"spender_threshold_{preview.meta.room_id}.html"
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )