"""学期相关查询，供管理员端和学生端共用。"""
from flask import current_app

from extensions import db
from models import ScoreRecord, Setting


def current_semester() -> str:
    """返回系统当前学期；未设置时使用应用默认值。"""
    return Setting.get("current_semester", current_app.config["DEFAULT_SEMESTER"])


def all_semesters() -> list[str]:
    """返回系统出现过的全部学期，当前学期始终排在最前。"""
    rows = (db.session.query(ScoreRecord.semester)
            .distinct()
            .order_by(ScoreRecord.semester.desc())
            .all())
    return _with_current([row[0] for row in rows])


def semesters_for_student(student_id: int) -> list[str]:
    """返回某位学生有记录的学期，当前学期始终包含在结果中。"""
    rows = (db.session.query(ScoreRecord.semester)
            .filter(ScoreRecord.student_id == student_id)
            .distinct()
            .order_by(ScoreRecord.semester.desc())
            .all())
    return _with_current([row[0] for row in rows])


def _with_current(semesters: list[str]) -> list[str]:
    current = current_semester()
    if current and current not in semesters:
        semesters.insert(0, current)
    return semesters
