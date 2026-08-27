"""排名榜算法（隐私保护版）。

- 不暴露任何他人姓名/学号
- 仅展示前 3 名分数 + 当前学生百分位 + 整体分布直方图
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from extensions import db
from models import ScoreRecord, Student


def build_full_roster(semester: str) -> dict:
    """构造全员加分透视表：学生为行、活动为列。"""
    students = Student.query.order_by(Student.student_no.asc()).all()
    activity_rows = (db.session.query(
                        ScoreRecord.activity_name,
                        func.min(ScoreRecord.created_at).label("first_at"))
                     .filter(ScoreRecord.semester == semester,
                             ScoreRecord.is_revoked.is_(False))
                     .group_by(ScoreRecord.activity_name)
                     .order_by(func.min(ScoreRecord.created_at).asc())
                     .all())
    activities = [row[0] for row in activity_rows]

    records = (ScoreRecord.query
               .filter(ScoreRecord.semester == semester,
                       ScoreRecord.is_revoked.is_(False))
               .all())
    pivot: dict[int, dict[str, Decimal]] = {}
    totals: dict[int, Decimal] = {}
    for record in records:
        pivot.setdefault(record.student_id, {})[record.activity_name] = record.points
        totals[record.student_id] = (
            totals.get(record.student_id, Decimal(0)) + record.points
        )

    return {
        "roster_students": students,
        "roster_activities": activities,
        "roster_pivot": pivot,
        "roster_totals": totals,
    }


def compute_totals(semester: str) -> list[tuple[int, Decimal]]:
    """返回 [(student_id, total_points)]，按总分降序。

    包括所有学生（即使没有任何加分，记 0 分），用于稳定的"超过百分比"计算。
    """
    rows = (db.session.query(
                Student.id,
                func.coalesce(func.sum(ScoreRecord.points), 0).label("total"))
            .outerjoin(ScoreRecord,
                       (ScoreRecord.student_id == Student.id)
                       & (ScoreRecord.semester == semester)
                       & (ScoreRecord.is_revoked.is_(False)))
            .group_by(Student.id)
            .all())
    return [(int(sid), Decimal(t or 0)) for sid, t in rows]


def build_histogram(totals: list[Decimal], bin_size: float = 1.0,
                    your_value: Optional[Decimal] = None) -> list[dict]:
    """按 bin_size 分桶，返回 [{label, low, high, count, is_you}]。"""
    if not totals:
        return []
    max_v = max(float(t) for t in totals)
    buckets: list[dict] = []
    edge = 0.0
    while edge <= max_v + 0.0001:
        low = edge
        high = edge + bin_size
        count = sum(1 for t in totals if low <= float(t) < high)
        is_you = False
        if your_value is not None and low <= float(your_value) < high:
            is_you = True
        buckets.append({
            "label": f"{low:.1f}+",
            "low": low, "high": high, "count": count, "is_you": is_you,
        })
        edge = high
    # 倒序：分高的桶在上面
    buckets.reverse()
    # 计算每个桶相对最大 count 的宽度比例
    max_count = max((b["count"] for b in buckets), default=1) or 1
    for b in buckets:
        b["pct"] = round(b["count"] / max_count * 100, 1)
    return buckets


def build_ranking_view(semester: str, my_student_id: int) -> dict:
    """返回排名页所需的所有数据。

    返回字段：
        n              本学期总人数（即名单总人数）
        top3           [{rank, points}]，最多 3 项（分数=Decimal，匿名）
        my_rank        我的排名（同分并列时取较好排名）
        my_points      我的总分
        my_percentile  超过的百分比（0-100 整数）
        histogram      [{label, count, pct, is_you}]
        rank_band      "top10" / "top30" / "top50" / "rest"，用于色调微调
    """
    totals = compute_totals(semester)
    n = len(totals)
    if n == 0:
        return {
            "n": 0, "top3": [],
            "my_rank": 0, "my_points": Decimal(0),
            "my_percentile": 0, "histogram": [], "rank_band": "rest",
        }

    sorted_desc = sorted(totals, key=lambda x: x[1], reverse=True)
    top3 = []
    for i, (_, pts) in enumerate(sorted_desc[:3], start=1):
        top3.append({"rank": i, "points": pts})

    me_pts = next((p for sid, p in totals if sid == my_student_id), Decimal(0))
    # 严格大于我的人数 → 我的排名 = better_count + 1
    better_count = sum(1 for _, p in totals if p > me_pts)
    my_rank = better_count + 1
    # 严格小于我的人数 / 总人数 = 超过的百分比（除自己以外）
    if n > 1:
        worse = sum(1 for _, p in totals if p < me_pts)
        my_percentile = round(worse / (n - 1) * 100)
    else:
        my_percentile = 0

    histogram = build_histogram([p for _, p in totals], 1.0, me_pts)

    band = "rest"
    if my_rank <= max(1, n * 0.10):
        band = "top10"
    elif my_rank <= max(1, n * 0.30):
        band = "top30"
    elif my_rank <= max(1, n * 0.50):
        band = "top50"

    return {
        "n": n,
        "top3": top3,
        "my_rank": my_rank,
        "my_points": me_pts,
        "my_percentile": my_percentile,
        "histogram": histogram,
        "rank_band": band,
    }
