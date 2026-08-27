"""管理员端：导出、账号、日志和系统设置。"""
from flask import (
    abort, flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user, login_required

from extensions import db
from models import Admin, AssignmentRule, AuditLog, Notification, Setting, Student
from services.audit import log as audit_log
from services.semesters import all_semesters, current_semester

from blueprints.admin import bp, super_required

@bp.route("/export")
@login_required
def export_page():
    return render_template("admin/export.html",
                           semesters=all_semesters(),
                           current_sem=current_semester())


@bp.route("/export/excel")
@login_required
def export_excel():
    from services.exporter import export_records_xlsx
    sem = request.args.get("semester") or current_semester()
    bio, filename = export_records_xlsx(sem)
    audit_log("export_excel", semester=sem)
    db.session.commit()
    return send_file(bio, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/export/db")
@login_required
def export_db():
    from config import INSTANCE_DIR
    audit_log("export_db")
    db.session.commit()
    return send_from_directory(
        INSTANCE_DIR, "scoring.db", as_attachment=True,
        download_name=f"scoring-{datetime.now().strftime('%Y%m%d-%H%M')}.db",
    )


# ---------- 管理员管理（仅主管） ----------

@bp.route("/admins")
@login_required
@super_required
def admins_list():
    return redirect(url_for("admin.settings"))


@bp.route("/admins/invite", methods=["POST"])
@login_required
@super_required
def admins_invite():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    is_super = bool(request.form.get("is_super"))
    if len(username) < 3 or len(password) < 8:
        flash("用户名至少 3 位，密码至少 8 位", "warning")
        return redirect(url_for("admin.settings"))
    if Admin.query.filter_by(username=username).first():
        flash("该用户名已存在", "warning")
        return redirect(url_for("admin.settings"))
    a = Admin(username=username, is_super=is_super)
    a.set_password(password)
    db.session.add(a)
    audit_log("invite_admin", target_type="admin", username=username, is_super=is_super)
    db.session.commit()
    flash(f"已添加管理员：{username}", "success")
    return redirect(url_for("admin.settings"))


@bp.route("/admins/<int:aid>/delete", methods=["POST"])
@login_required
@super_required
def admins_delete(aid: int):
    a = db.session.get(Admin, aid) or abort(404)
    if a.id == current_user.id:
        flash("不能删除自己", "danger")
        return redirect(url_for("admin.settings"))
    if a.is_super and Admin.query.filter_by(is_super=True).count() <= 1:
        flash("必须保留至少一个主管", "danger")
        return redirect(url_for("admin.settings"))
    audit_log("delete_admin", target_type="admin", target_id=a.id, username=a.username)
    db.session.delete(a)
    db.session.commit()
    flash("已删除", "success")
    return redirect(url_for("admin.settings"))


# ---------- 审计日志 ----------

@bp.route("/logs")
@login_required
def logs():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 50
    pagination = (AuditLog.query.order_by(AuditLog.created_at.desc())
                  .paginate(page=page, per_page=per_page, error_out=False))
    return render_template("admin/logs.html", pagination=pagination)


# ---------- 设置（仅主管） ----------

@bp.route("/settings")
@login_required
@super_required
def settings():
    admins = Admin.query.order_by(Admin.is_super.desc(), Admin.created_at.asc()).all()
    rules = AssignmentRule.query.order_by(AssignmentRule.start_no.asc()).all()
    return render_template("admin/settings.html", admins=admins, rules=rules,
                           current_sem=current_semester())


@bp.route("/settings/semester", methods=["POST"])
@login_required
@super_required
def settings_semester():
    semester = (request.form.get("semester") or "").strip()
    if not 3 <= len(semester) <= 32:
        flash("学期名称需要 3~32 个字符", "warning")
        return redirect(url_for("admin.settings"))
    old = current_semester()
    if semester == old:
        flash("这已经是当前学期", "warning")
        return redirect(url_for("admin.settings"))
    Setting.set("current_semester", semester)
    for student_id, in db.session.query(Student.id).all():
        db.session.add(Notification(
            student_id=student_id,
            content=f"新学期 {semester} 已开启，加分和申报将记入新学期。",
        ))
    audit_log("start_semester", before=old, after=semester)
    db.session.commit()
    flash(f"已开启新学期：{semester}", "success")
    return redirect(url_for("admin.settings"))


@bp.route("/settings/assignment-rules", methods=["POST"])
@login_required
@super_required
def assignment_rule_add():
    start_no = (request.form.get("start_no") or "").strip()
    end_no = (request.form.get("end_no") or "").strip()
    admin_id = request.form.get("admin_id", type=int)
    admin = db.session.get(Admin, admin_id) if admin_id else None
    if not start_no or not end_no or start_no > end_no or not admin:
        flash("请填写正确的学号起止范围并选择管理员", "warning")
        return redirect(url_for("admin.settings"))
    rule = AssignmentRule(start_no=start_no, end_no=end_no, admin_id=admin.id)
    db.session.add(rule)
    audit_log("add_assignment_rule", start_no=start_no, end_no=end_no,
              admin_id=admin.id)
    db.session.commit()
    flash(f"已将学号 {start_no} 至 {end_no} 分配给 {admin.username}", "success")
    return redirect(url_for("admin.settings"))


@bp.route("/settings/assignment-rules/<int:rule_id>/delete", methods=["POST"])
@login_required
@super_required
def assignment_rule_delete(rule_id: int):
    rule = db.session.get(AssignmentRule, rule_id) or abort(404)
    audit_log("delete_assignment_rule", target_type="assignment_rule",
              target_id=rule.id)
    db.session.delete(rule)
    db.session.commit()
    flash("分配规则已删除", "success")
    return redirect(url_for("admin.settings"))
