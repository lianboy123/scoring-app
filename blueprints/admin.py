"""管理员端蓝图入口：认证、仪表盘和子模块注册。"""
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from extensions import db
from models import Admin, ScoreRecord, Student
from services.audit import log as audit_log
from services.categories import SCORING_CATEGORIES
from services.semesters import all_semesters, current_semester


bp = Blueprint("admin", __name__, url_prefix="/admin")

def super_required(view):
    """仅允许主管管理员访问。"""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_super:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@bp.app_context_processor
def inject_admin_globals():
    authenticated = current_user.is_authenticated
    return {
        "current_semester_value": current_semester() if authenticated else None,
        "all_semesters": all_semesters() if authenticated else [],
        "scoring_categories": SCORING_CATEGORIES,
    }


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            login_user(admin, remember=False)
            audit_log("admin_login", target_type="admin", target_id=admin.id)
            db.session.commit()
            return redirect(url_for("admin.dashboard"))
        flash("用户名或密码错误", "danger")
    return render_template("admin/login.html")


@bp.route("/logout")
@login_required
def logout():
    audit_log("admin_logout", target_type="admin", target_id=current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for("admin.login"))


# ---------- 主页 ----------

@bp.route("/")
@login_required
def dashboard():
    sem = current_semester()
    student_count = db.session.query(func.count(Student.id)).scalar() or 0
    activity_count = (db.session.query(func.count(func.distinct(ScoreRecord.activity_name)))
                      .filter(ScoreRecord.semester == sem,
                              ScoreRecord.is_revoked.is_(False)).scalar() or 0)
    recent_activities = (db.session.query(
                            ScoreRecord.activity_name,
                            func.count(ScoreRecord.id).label("participant_count"),
                            func.sum(ScoreRecord.points).label("total_points"),
                            func.min(ScoreRecord.points).label("min_points"),
                            func.max(ScoreRecord.points).label("max_points"),
                            func.max(ScoreRecord.created_at).label("latest"))
                         .filter(ScoreRecord.semester == sem,
                                 ScoreRecord.is_revoked.is_(False))
                         .group_by(ScoreRecord.activity_name)
                         .order_by(func.max(ScoreRecord.created_at).desc())
                         .limit(5).all())
    return render_template("admin/dashboard.html",
                           student_count=student_count,
                           activity_count=activity_count,
                           recent_activities=recent_activities)
# 导入即注册其余管理员路由；按业务拆分后，每个文件只负责一个领域。
from blueprints import admin_claims, admin_scores, admin_students, admin_system  # noqa: E402,F401
