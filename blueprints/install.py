"""首次部署初始化主管账号。

仅当 Admin 表为空时可访问；否则一律返回 403。
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from extensions import db
from models import Admin, Setting
from services.audit import log as audit_log

bp = Blueprint("install", __name__)


def _no_admin_yet() -> bool:
    return db.session.query(Admin.id).first() is None


@bp.route("/install", methods=["GET", "POST"])
def install():
    if not _no_admin_yet():
        return ("系统已初始化，无法重复访问该页面。", 403)

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        semester = (request.form.get("semester") or "").strip()

        errors = []
        if not username or len(username) < 3:
            errors.append("用户名至少 3 个字符")
        if not password or len(password) < 8:
            errors.append("密码至少 8 个字符")
        if password != confirm:
            errors.append("两次密码不一致")
        if not semester:
            errors.append("请填写当前学期标识，如 2026-spring")

        if errors:
            for msg in errors:
                flash(msg, "danger")
            return render_template("install.html",
                                   username=username, semester=semester)

        admin = Admin(username=username, is_super=True)
        admin.set_password(password)
        db.session.add(admin)
        Setting.set("current_semester", semester)
        audit_log("install", target_type="admin", target_id=None,
                  username=username, semester=semester)
        db.session.commit()

        flash("初始化完成，请使用刚才创建的账号登录管理后台。", "success")
        return redirect(url_for("admin.login"))

    return render_template("install.html")
