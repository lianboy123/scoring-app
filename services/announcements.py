"""活动加分公示：按 (学期, 活动名称) 聚合有效 ScoreRecord。

只读派生视图：完全基于现有 ScoreRecord（is_revoked=False）聚合，不引入新表。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func

from extensions import db
from models import ScoreRecord, Student


def list_announcements(semester: str) -> list[dict]:
    """某学期的所有公示摘要，按最近加分时间倒序。

    返回：[{activity, latest, count, total_points, max_points}]
    """
    rows = (db.session.query(
                ScoreRecord.activity_name.label("activity"),
                func.max(ScoreRecord.created_at).label("latest"),
                func.count(ScoreRecord.id).label("cnt"),
                func.coalesce(func.sum(ScoreRecord.points), 0).label("total"),
                func.max(ScoreRecord.points).label("max_pts"),
            )
            .filter(ScoreRecord.semester == semester,
                    ScoreRecord.is_revoked.is_(False))
            .group_by(ScoreRecord.activity_name)
            .order_by(func.max(ScoreRecord.created_at).desc())
            .all())
    return [
        {
            "activity": r.activity,
            "latest": r.latest,
            "count": int(r.cnt or 0),
            "total_points": Decimal(r.total or 0),
            "max_points": Decimal(r.max_pts or 0),
        }
        for r in rows
    ]


def get_announcement_rows(semester: str, activity: str) -> list[tuple[ScoreRecord, Student]]:
    """单条公示的完整参与名单，按分值倒序、同分按姓名升序。"""
    return (db.session.query(ScoreRecord, Student)
            .join(Student, Student.id == ScoreRecord.student_id)
            .filter(ScoreRecord.semester == semester,
                    ScoreRecord.activity_name == activity,
                    ScoreRecord.is_revoked.is_(False))
            .order_by(ScoreRecord.points.desc(), Student.name.asc())
            .all())
