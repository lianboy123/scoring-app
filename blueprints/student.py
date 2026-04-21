"""学生端蓝图。

学号+姓名免密登录，会话仅维持当前浏览器进程。
3 个底部 Tab 页面：首页 / 排名 / 我。
"""
from __future__ import annotations

from decimal import Decimal
from functools import wraps

from flask import (
    Blueprint, current_app, flash, jsonify, redirect, render_template,
    request, session, url_for,
)
from sqlalchemy import func

from extensions import db
from models import Notification, ScoreRecord, Setting, Student


bp = Blueprint("student", __name__)


# ---------- 工具 ----------

def current_semester() -> str:
    return Setting.get("current_semester", current_app.config["DEFAULT_SEMESTER"])


def all_semesters_for_student(sid: int) -> list[str]:
    rows = (db.session.query(ScoreRecord.semester)
            .filter(ScoreRecord.student_id == sid)
            .distinct().order_by(ScoreRecord.semester.desc()).all())
    sems = [r[0] for r in rows]
    cur = current_semester()
    if cur and cur not in sems:
        sems.insert(0, cur)
    return sems


def get_current_student() -> Student | None:
    sid = session.get("student_id")
    if not sid:
        return None
    return db.session.get(Student, sid)


def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not get_current_student():
            return redirect(url_for("student.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@bp.app_context_processor
def inject_student_globals():
    s = get_current_student()
    if not s:
        return {"current_student": None, "unread_count": 0}
    unread = (db.session.query(func.count(Notification.id))
              .filter(Notification.student_id == s.id,
                      Notification.is_read.is_(False)).scalar() or 0)
    return {"current_student": s, "unread_count": unread}


# ---------- 路由 ----------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if get_current_student():
        return redirect(url_for("student.home"))
    if request.method == "POST":
        no = (request.form.get("student_no") or "").strip()
        name = (request.form.get("name") or "").strip()
        if not no or not name:
            flash("请填写学号和姓名", "warning")
        else:
            s = Student.query.filter_by(student_no=no, name=name).first()
            if s:
                session["student_id"] = s.id
                # 不持久化（关浏览器即失效）
                session.permanent = False
                target = request.args.get("next") or url_for("student.home")
                return redirect(target)
            flash("学号或姓名不正确，或你不在本学期名单中。请联系管理员核对。", "danger")
    return render_template("student/login.html")


@bp.route("/logout")
def logout():
    session.pop("student_id", None)
    return redirect(url_for("student.login"))


@bp.route("/")
@student_required
def home():
    s = get_current_student()
    sem = current_semester()
    total = (db.session.query(func.coalesce(func.sum(ScoreRecord.points), 0))
             .filter(ScoreRecord.student_id == s.id,
                     ScoreRecord.semester == sem,
                     ScoreRecord.is_revoked.is_(False))
             .scalar()) or 0
    record_count = (db.session.query(func.count(ScoreRecord.id))
                    .filter(ScoreRecord.student_id == s.id,
                            ScoreRecord.semester == sem,
                            ScoreRecord.is_revoked.is_(False)).scalar()) or 0
    recent = (ScoreRecord.query
              .filter_by(student_id=s.id, semester=sem, is_revoked=False)
              .order_by(ScoreRecord.created_at.desc())
              .limit(5).all())
    return render_template("student/home.html",
                           total=total, record_count=record_count,
                           recent=recent, sem=sem)


@bp.route("/ranking")
@student_required
def ranking():
    from services.ranking import build_ranking_view

    s = get_current_student()
    sem = current_semester()
    view = build_ranking_view(sem, s.id)
    return render_template("student/ranking.html", sem=sem, **view)


@bp.route("/me")
@student_required
def me():
    s = get_current_student()
    sems = all_semesters_for_student(s.id) or [current_semester()]
    sem = request.args.get("semester") or sems[0]
    records = (ScoreRecord.query
               .filter_by(student_id=s.id, semester=sem, is_revoked=False)
               .order_by(ScoreRecord.created_at.desc()).all())
    total = sum((r.points for r in records), Decimal("0"))
    notifications = (Notification.query
                     .filter_by(student_id=s.id)
                     .order_by(Notification.created_at.desc())
                     .limit(50).all())
    return render_template("student/me.html",
                           records=records, total=total,
                           notifications=notifications,
                           sem=sem, semesters=sems)


@bp.route("/notifications/read", methods=["POST"])
def mark_notifications_read():
    s = get_current_student()
    if not s:
        return jsonify({"ok": False}), 401
    Notification.query.filter_by(student_id=s.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/notifications/unread_count")
def unread_count():
    s = get_current_student()
    if not s:
        return jsonify({"count": 0})
    n = (db.session.query(func.count(Notification.id))
         .filter(Notification.student_id == s.id,
                 Notification.is_read.is_(False)).scalar() or 0)
    return jsonify({"count": int(n)})
