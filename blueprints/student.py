"""学生端蓝图。

学号+姓名免密登录，会话仅维持当前浏览器进程。
3 个底部 Tab 页面：首页 / 公示 / 申报。
"""
from __future__ import annotations

from decimal import Decimal
from functools import wraps
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
    request, send_from_directory, session, url_for,
)
from flask_login import current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename

from extensions import db
from models import Admin, AssignmentRule, Claim, Notification, ScoreRecord, Student
from services.announcements import get_announcement_rows, list_announcements
from services.categories import CATEGORY_MAP, CLAIMABLE_CATEGORIES, SCORING_CATEGORIES
from services.semesters import current_semester, semesters_for_student


bp = Blueprint("student", __name__)


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
    rows = (db.session.query(ScoreRecord.category,
                             func.coalesce(func.sum(ScoreRecord.points), 0))
            .filter(ScoreRecord.student_id == s.id,
                    ScoreRecord.semester == sem,
                    ScoreRecord.is_revoked.is_(False))
            .group_by(ScoreRecord.category).all())
    totals_map = {category: Decimal(total or 0) for category, total in rows}
    category_totals = [
        {**item, "points": totals_map.get(item["slug"], Decimal("0"))}
        for item in SCORING_CATEGORIES
    ]
    total = sum((item["points"] for item in category_totals), Decimal("0"))
    latest_announcements = list_announcements(sem)[:3]
    notifications = (Notification.query.filter_by(student_id=s.id)
                     .order_by(Notification.created_at.desc()).limit(5).all())

    return render_template("student/home.html",
                           total=total, category_totals=category_totals, sem=sem,
                           latest_announcements=latest_announcements,
                           notifications=notifications)


@bp.route("/announcements")
@student_required
def announcements():
    """活动加分公示：按 (学期, 活动名称) 聚合。"""
    s = get_current_student()
    sems = semesters_for_student(s.id)
    sem = request.args.get("semester") or sems[0]

    summaries = list_announcements(sem)
    # 组装每条公示的完整名单，供模板一次性渲染（学期内活动数与人数规模都很小）
    items = []
    for item in summaries:
        rows = get_announcement_rows(sem, item["activity"])
        items.append({**item, "rows": rows})

    return render_template("student/announcements.html",
                           items=items, sem=sem, semesters=sems)


@bp.route("/ranking")
@student_required
def ranking():
    sem = current_semester()
    students = Student.query.order_by(Student.student_no.asc()).all()
    records = (ScoreRecord.query
               .filter_by(semester=sem, is_revoked=False, is_public=True).all())
    totals: dict[int, dict[str, Decimal]] = {}
    for record in records:
        student_totals = totals.setdefault(record.student_id, {})
        student_totals[record.category] = (
            student_totals.get(record.category, Decimal("0")) + record.points
        )
    grand_totals = {
        sid: sum(category_values.values(), Decimal("0"))
        for sid, category_values in totals.items()
    }
    return render_template("student/public.html", sem=sem, students=students,
                           categories=SCORING_CATEGORIES, totals=totals,
                           grand_totals=grand_totals)


@bp.route("/public/student/<int:student_id>/<category>")
@student_required
def public_student_category(student_id: int, category: str):
    student = db.session.get(Student, student_id) or abort(404)
    if category not in CATEGORY_MAP:
        abort(404)
    sem = current_semester()
    records = (ScoreRecord.query
               .filter_by(student_id=student.id, semester=sem,
                          category=category, is_revoked=False, is_public=True)
               .order_by(ScoreRecord.created_at.desc()).all())
    return render_template("student/public_detail.html", student=student,
                           category=category, category_label=CATEGORY_MAP[category],
                           records=records, sem=sem)


def _assigned_admin(student_no: str) -> Admin | None:
    rules = AssignmentRule.query.order_by(AssignmentRule.start_no.asc()).all()
    for rule in rules:
        if rule.start_no <= student_no <= rule.end_no:
            return rule.admin
    return Admin.query.filter_by(is_super=True).order_by(Admin.id.asc()).first()


@bp.route("/claims", methods=["GET", "POST"])
@student_required
def claims():
    student = get_current_student()
    if request.method == "POST":
        category = (request.form.get("category") or "").strip()
        title = (request.form.get("title") or "").strip()[:255]
        proof = request.files.get("proof")
        allowed = {"jpg", "jpeg", "png", "webp"}
        ext = secure_filename(proof.filename).rsplit(".", 1)[-1].lower() if proof and proof.filename and "." in proof.filename else ""
        if category not in {item["slug"] for item in CLAIMABLE_CATEGORIES}:
            flash("请选择可申报的加分类别", "warning")
        elif not title:
            flash("请填写申报项目名称", "warning")
        elif not proof or ext not in allowed or not (proof.mimetype or "").startswith("image/"):
            flash("证明材料只支持 JPG、PNG 或 WEBP 图片", "warning")
        else:
            upload_dir = Path(current_app.config["CLAIM_UPLOAD_DIR"])
            upload_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{uuid4().hex}.{ext}"
            proof.save(upload_dir / filename)
            assigned = _assigned_admin(student.student_no)
            claim = Claim(student_id=student.id, category=category, title=title,
                          image_filename=filename, semester=current_semester(),
                          assigned_admin_id=assigned.id if assigned else None)
            db.session.add(claim)
            db.session.commit()
            flash("申报已提交，审核结果会通过通知告诉你", "success")
            return redirect(url_for("student.claims"))
    items = (Claim.query.filter_by(student_id=student.id)
             .order_by(Claim.created_at.desc()).all())
    return render_template("student/claims.html", claims=items,
                           categories=CLAIMABLE_CATEGORIES,
                           category_map=CATEGORY_MAP)


@bp.route("/claims/<int:claim_id>/image")
def claim_image(claim_id: int):
    claim = db.session.get(Claim, claim_id) or abort(404)
    student = get_current_student()
    admin_allowed = (current_user.is_authenticated and
                     (current_user.is_super or claim.assigned_admin_id == current_user.id))
    if not admin_allowed and (not student or claim.student_id != student.id):
        abort(403)
    return send_from_directory(current_app.config["CLAIM_UPLOAD_DIR"],
                               claim.image_filename)


@bp.route("/me")
@student_required
def me():
    return redirect(url_for("student.home"))


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
