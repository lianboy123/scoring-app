"""管理员端蓝图。

涵盖：登录、仪表盘、学生名单、上传/审核、记录、导出/备份、管理员管理、日志、设置。
为减少文件数量，所有 admin 路由集中在此模块。
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime
from decimal import Decimal
from functools import wraps

from flask import (
    Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
    request, send_file, send_from_directory, url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from extensions import db
from models import (
    Admin, AuditLog, Notification, ScoreRecord, Setting, Student, UploadBatch,
)
from services.audit import log as audit_log
from services.parser import ParseError, parse_roster, parse_score_file


bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------- 工具 ----------

def super_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_super:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def current_semester() -> str:
    return Setting.get("current_semester", current_app.config["DEFAULT_SEMESTER"])


def all_semesters() -> list[str]:
    rows = (db.session.query(ScoreRecord.semester)
            .distinct().order_by(ScoreRecord.semester.desc()).all())
    semesters = [r[0] for r in rows]
    cur = current_semester()
    if cur and cur not in semesters:
        semesters.insert(0, cur)
    return semesters


@bp.app_context_processor
def inject_admin_globals():
    return {
        "current_semester_value": current_semester() if current_user.is_authenticated else None,
        "all_semesters": all_semesters() if current_user.is_authenticated else [],
    }


# ---------- 登录 / 登出 ----------

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


# ---------- 仪表盘 ----------

@bp.route("/")
@login_required
def dashboard():
    sem = current_semester()
    student_count = db.session.query(func.count(Student.id)).scalar()
    pending_batches = (db.session.query(func.count(UploadBatch.id))
                       .filter(UploadBatch.status == "pending").scalar())
    record_count = (db.session.query(func.count(ScoreRecord.id))
                    .filter(ScoreRecord.semester == sem,
                            ScoreRecord.is_revoked.is_(False)).scalar())
    total_points = (db.session.query(func.coalesce(func.sum(ScoreRecord.points), 0))
                    .filter(ScoreRecord.semester == sem,
                            ScoreRecord.is_revoked.is_(False)).scalar())
    recent_batches = (UploadBatch.query
                      .order_by(UploadBatch.uploaded_at.desc()).limit(5).all())
    return render_template("admin/dashboard.html",
                           student_count=student_count,
                           pending_batches=pending_batches,
                           record_count=record_count,
                           total_points=total_points or 0,
                           recent_batches=recent_batches)


# ---------- 学生名单 ----------

@bp.route("/students")
@login_required
def students():
    q = (request.args.get("q") or "").strip()
    query = Student.query.order_by(Student.student_no.asc())
    if q:
        like = f"%{q}%"
        query = query.filter((Student.student_no.like(like)) | (Student.name.like(like)))
    items = query.all()
    return render_template("admin/students.html", students=items, q=q)


@bp.route("/students/import", methods=["POST"])
@login_required
def students_import():
    f = request.files.get("file")
    if not f or not f.filename:
        flash("请选择要导入的文件", "warning")
        return redirect(url_for("admin.students"))

    raw = f.read()
    try:
        rows = parse_roster(f.filename, raw)
    except ParseError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.students"))

    inserted, updated, skipped = 0, 0, 0
    for row in rows:
        no, name = row["student_no"], row["name"]
        existing = Student.query.filter_by(student_no=no).first()
        if existing:
            if existing.name != name:
                existing.name = name
                updated += 1
            else:
                skipped += 1
        else:
            db.session.add(Student(student_no=no, name=name))
            inserted += 1
    audit_log("import_students", target_type="student",
              filename=f.filename, inserted=inserted, updated=updated, skipped=skipped)
    db.session.commit()
    flash(f"导入完成：新增 {inserted} 人，更新 {updated} 人，已存在 {skipped} 人。", "success")
    return redirect(url_for("admin.students"))


@bp.route("/students/add", methods=["POST"])
@login_required
def students_add():
    no = (request.form.get("student_no") or "").strip()
    name = (request.form.get("name") or "").strip()
    if not no or not name:
        flash("学号和姓名不能为空", "warning")
        return redirect(url_for("admin.students"))
    if Student.query.filter_by(student_no=no).first():
        flash(f"学号 {no} 已存在", "warning")
        return redirect(url_for("admin.students"))
    s = Student(student_no=no, name=name)
    db.session.add(s)
    audit_log("add_student", target_type="student", student_no=no, name=name)
    db.session.commit()
    flash(f"已新增学生：{name}（{no}）", "success")
    return redirect(url_for("admin.students"))


@bp.route("/students/<int:sid>/edit", methods=["POST"])
@login_required
def students_edit(sid: int):
    s = db.session.get(Student, sid) or abort(404)
    new_no = (request.form.get("student_no") or "").strip()
    new_name = (request.form.get("name") or "").strip()
    if not new_no or not new_name:
        flash("学号和姓名不能为空", "warning")
        return redirect(url_for("admin.students"))
    if new_no != s.student_no and Student.query.filter_by(student_no=new_no).first():
        flash(f"学号 {new_no} 已存在", "warning")
        return redirect(url_for("admin.students"))
    audit_log("edit_student", target_type="student", target_id=s.id,
              before={"no": s.student_no, "name": s.name},
              after={"no": new_no, "name": new_name})
    s.student_no, s.name = new_no, new_name
    db.session.commit()
    flash("已保存", "success")
    return redirect(url_for("admin.students"))


@bp.route("/students/<int:sid>/delete", methods=["POST"])
@login_required
def students_delete(sid: int):
    s = db.session.get(Student, sid) or abort(404)
    has_records = db.session.query(ScoreRecord.id).filter_by(student_id=sid).first()
    if has_records:
        flash(f"{s.name}（{s.student_no}）已有加分记录，不能删除。请改为修改或保留。", "warning")
        return redirect(url_for("admin.students"))
    audit_log("delete_student", target_type="student", target_id=s.id,
              student_no=s.student_no, name=s.name)
    db.session.delete(s)
    db.session.commit()
    flash("已删除", "success")
    return redirect(url_for("admin.students"))


# ---------- 上传 / 审核 ----------

@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("请选择文件", "warning")
            return redirect(url_for("admin.upload"))
        sem = (request.form.get("semester") or current_semester()).strip()
        raw = f.read()
        try:
            rows, warnings = parse_score_file(f.filename, raw)
        except ParseError as e:
            flash(str(e), "danger")
            return redirect(url_for("admin.upload"))
        if not rows:
            flash("文件中没有可解析的数据行", "warning")
            return redirect(url_for("admin.upload"))

        # 状态标注：ok / no_match / duplicate / error
        for row in rows:
            if row["parse_error"]:
                row["status"] = "error"
                continue
            student = Student.query.filter_by(student_no=row["student_no"]).first()
            if not student:
                row["status"] = "no_match"
                row["student_id"] = None
                continue
            row["student_id"] = student.id
            existing = (ScoreRecord.query
                        .filter_by(student_id=student.id,
                                   activity_name=row["activity_name"],
                                   semester=sem,
                                   is_revoked=False).first())
            row["status"] = "duplicate" if existing else "ok"
            row["existing_id"] = existing.id if existing else None
            # 修正名字显示，用名单里的名字（防止文件中名字写错）
            row["matched_name"] = student.name

        batch = UploadBatch(
            filename=f.filename, uploader_id=current_user.id, semester=sem,
            status="pending", total_rows=len(rows),
            parsed_json=json.dumps({"rows": rows, "warnings": warnings},
                                   ensure_ascii=False, default=str),
        )
        db.session.add(batch)
        audit_log("upload_batch", target_type="batch", filename=f.filename,
                  semester=sem, total_rows=len(rows))
        db.session.commit()
        return redirect(url_for("admin.batch_review", batch_id=batch.id))

    return render_template("admin/upload.html",
                           current_sem=current_semester())


@bp.route("/batch/<int:batch_id>")
@login_required
def batch_review(batch_id: int):
    batch = db.session.get(UploadBatch, batch_id) or abort(404)
    payload = json.loads(batch.parsed_json or '{"rows":[],"warnings":[]}')
    return render_template("admin/batch_review.html",
                           batch=batch, rows=payload["rows"],
                           warnings=payload.get("warnings", []))


@bp.route("/batch/<int:batch_id>/approve", methods=["POST"])
@login_required
def batch_approve(batch_id: int):
    batch = db.session.get(UploadBatch, batch_id) or abort(404)
    if batch.status != "pending":
        flash("该批次已处理，无法重复入库", "warning")
        return redirect(url_for("admin.batch_review", batch_id=batch_id))

    payload = json.loads(batch.parsed_json or '{"rows":[]}')
    rows = payload["rows"]

    # 接收前端勾选：哪些行入库 + 哪些 duplicate 行确认覆盖
    selected = set(request.form.getlist("approve_idx"))
    overwrite = set(request.form.getlist("overwrite_idx"))

    send_notify = bool(request.form.get("send_notify"))

    inserted, overwritten = 0, 0
    new_record_ids_per_student: dict[int, list[int]] = {}
    all_new_ids: list[int] = []
    overwritten_old_ids: list[int] = []

    for i, row in enumerate(rows):
        idx = str(i)
        if idx not in selected:
            continue
        if row["status"] == "error" or not row.get("student_id"):
            continue
        if row["status"] == "duplicate" and idx not in overwrite:
            continue

        try:
            points = Decimal(str(row["points"]))
        except Exception:
            continue

        if row["status"] == "duplicate" and row.get("existing_id"):
            existing = db.session.get(ScoreRecord, row["existing_id"])
            if existing:
                existing.is_revoked = True
                existing.revoked_at = datetime.utcnow()
                existing.revoked_by = current_user.id
                overwritten += 1
                overwritten_old_ids.append(existing.id)
                db.session.flush()  # 让部分唯一索引先看到旧行已撤销

        record = ScoreRecord(
            student_id=row["student_id"],
            activity_name=row["activity_name"],
            points=points,
            semester=batch.semester,
            batch_id=batch.id,
            operator_id=current_user.id,
        )
        db.session.add(record)
        db.session.flush()  # 拿到 id
        new_record_ids_per_student.setdefault(row["student_id"], []).append(record.id)
        all_new_ids.append(record.id)
        inserted += 1

    if send_notify:
        for sid, rec_ids in new_record_ids_per_student.items():
            recs = ScoreRecord.query.filter(ScoreRecord.id.in_(rec_ids)).all()
            names = "、".join(r.activity_name for r in recs[:3])
            if len(recs) > 3:
                names += f" 等 {len(recs)} 项"
            total = sum((r.points for r in recs), Decimal("0"))
            db.session.add(Notification(
                student_id=sid,
                content=f"你新增了 {len(recs)} 条加分（{names}），合计 +{total} 分。",
            ))

    batch.status = "approved"
    batch.approved_rows = inserted
    audit_log("approve_batch", target_type="batch", target_id=batch.id,
              inserted=inserted, overwritten=overwritten, notify=send_notify,
              record_ids=all_new_ids, overwritten_ids=overwritten_old_ids)
    db.session.commit()
    notify_msg = "，已通知学生" if send_notify else "（未发通知）"
    flash(f"已入库 {inserted} 条（其中覆盖 {overwritten} 条）{notify_msg}。", "success")
    return redirect(url_for("admin.batch_review", batch_id=batch_id))


@bp.route("/batch/<int:batch_id>/rollback", methods=["POST"])
@login_required
def batch_rollback(batch_id: int):
    batch = db.session.get(UploadBatch, batch_id) or abort(404)
    if batch.status != "approved":
        flash("只有已入库的批次可以回滚", "warning")
        return redirect(url_for("admin.batch_review", batch_id=batch_id))

    affected = 0
    for r in batch.records.filter_by(is_revoked=False).all():
        r.is_revoked = True
        r.revoked_at = datetime.utcnow()
        r.revoked_by = current_user.id
        affected += 1
    batch.status = "rolled_back"
    audit_log("rollback_batch", target_type="batch", target_id=batch.id, affected=affected)
    db.session.commit()
    flash(f"已回滚批次，撤销 {affected} 条记录。", "success")
    return redirect(url_for("admin.batch_review", batch_id=batch_id))


# ---------- 加分记录 ----------

@bp.route("/records")
@login_required
def records():
    sem = request.args.get("semester") or current_semester()
    q = (request.args.get("q") or "").strip()
    show_revoked = request.args.get("revoked") == "1"

    query = (db.session.query(ScoreRecord, Student)
             .join(Student, Student.id == ScoreRecord.student_id)
             .filter(ScoreRecord.semester == sem))
    if not show_revoked:
        query = query.filter(ScoreRecord.is_revoked.is_(False))
    if q:
        like = f"%{q}%"
        query = query.filter((Student.student_no.like(like))
                             | (Student.name.like(like))
                             | (ScoreRecord.activity_name.like(like)))
    rows = query.order_by(ScoreRecord.created_at.desc()).limit(500).all()
    students_all = Student.query.order_by(Student.student_no.asc()).all()
    return render_template("admin/records.html",
                           rows=rows, sem=sem, q=q, show_revoked=show_revoked,
                           students_all=students_all)


@bp.route("/records/<int:rid>/restore", methods=["POST"])
@login_required
def records_restore(rid: int):
    """把已撤销的记录恢复为有效。"""
    r = db.session.get(ScoreRecord, rid) or abort(404)
    if not r.is_revoked:
        flash("该记录未被撤销，无需恢复", "warning")
        return redirect(request.referrer or url_for("admin.records"))

    # 防冲突：同学/同活动/同学期若已有其他有效记录，阻止恢复
    conflict = (ScoreRecord.query
                .filter(ScoreRecord.student_id == r.student_id,
                        ScoreRecord.activity_name == r.activity_name,
                        ScoreRecord.semester == r.semester,
                        ScoreRecord.is_revoked.is_(False),
                        ScoreRecord.id != r.id)
                .first())
    if conflict:
        flash(f"恢复失败：{r.activity_name} 当前已有有效记录（{conflict.points} 分），"
              f"请先撤销它再恢复。", "warning")
        return redirect(request.referrer or url_for("admin.records"))

    send_notify = bool(request.form.get("send_notify"))
    r.is_revoked = False
    r.revoked_at = None
    r.revoked_by = None
    if send_notify:
        db.session.add(Notification(
            student_id=r.student_id,
            content=f"你的加分已恢复：{r.activity_name} +{r.points} 分",
        ))
    audit_log("restore_record", target_type="score_record", target_id=r.id,
              activity=r.activity_name, points=str(r.points), notify=send_notify)
    db.session.commit()
    flash("已恢复" + ("，已通知学生" if send_notify else "（未发通知）"), "success")
    return redirect(request.referrer or url_for("admin.records"))


@bp.route("/records/bulk_delete", methods=["POST"])
@login_required
def records_bulk_delete():
    """物理永久删除选中的加分记录（不可恢复）。

    与「撤销」的区别：
    - 撤销：软删（is_revoked=True），可恢复，发通知
    - 永久删除：从 DB 抹除；学生端不会显示"撤销通知"；适合清理脏数据
    """
    ids = request.form.getlist("record_ids", type=int)
    if not ids:
        flash("没有选中任何记录", "warning")
        return redirect(request.referrer or url_for("admin.records"))

    records = ScoreRecord.query.filter(ScoreRecord.id.in_(ids)).all()
    deleted_summary = [
        {"id": r.id, "student_id": r.student_id,
         "activity": r.activity_name, "points": str(r.points),
         "semester": r.semester, "was_revoked": r.is_revoked}
        for r in records
    ]
    for r in records:
        db.session.delete(r)

    audit_log("bulk_delete_records", target_type="score_record",
              count=len(records), record_ids=[r["id"] for r in deleted_summary],
              records=deleted_summary)
    db.session.commit()
    flash(f"已永久删除 {len(records)} 条加分记录（不可恢复）。", "success")
    return redirect(request.referrer or url_for("admin.records"))


@bp.route("/records/<int:rid>/revoke", methods=["POST"])
@login_required
def records_revoke(rid: int):
    r = db.session.get(ScoreRecord, rid) or abort(404)
    if r.is_revoked:
        flash("该记录已撤销", "warning")
        return redirect(request.referrer or url_for("admin.records"))
    send_notify = bool(request.form.get("send_notify"))
    r.is_revoked = True
    r.revoked_at = datetime.utcnow()
    r.revoked_by = current_user.id
    if send_notify:
        db.session.add(Notification(
            student_id=r.student_id,
            content=f"你的加分被撤销：{r.activity_name}（-{r.points} 分）",
        ))
    audit_log("revoke_record", target_type="score_record", target_id=r.id,
              activity=r.activity_name, points=str(r.points), notify=send_notify)
    db.session.commit()
    flash("已撤销" + ("，已通知学生" if send_notify else "（未发通知）"), "success")
    return redirect(request.referrer or url_for("admin.records"))


# ---------- 手动加分（单人 / 批量按活动） ----------

def _parse_points(raw: str) -> Decimal | None:
    """把字符串解析成合法分值，失败返回 None。"""
    try:
        p = Decimal(str(raw).strip().replace("分", "").replace("＋", "+"))
    except Exception:
        return None
    if p < 0 or p > Decimal("99.99"):
        return None
    return p


def _add_score_for(student_id: int, activity: str, points: Decimal,
                   semester: str, overwrite: bool,
                   send_notify: bool = True) -> tuple[str, str, int | None, int | None]:
    """给单个学生写一条加分。

    返回 (status, msg, new_record_id, overwritten_record_id)。
    status: 'added' / 'overwritten' / 'duplicate' / 'skipped'
    """
    existing = (ScoreRecord.query
                .filter_by(student_id=student_id, activity_name=activity,
                           semester=semester, is_revoked=False).first())
    if existing and not overwrite:
        return "duplicate", f"已存在（{existing.points} 分）", None, None

    overwritten_id = None
    if existing and overwrite:
        existing.is_revoked = True
        existing.revoked_at = datetime.utcnow()
        existing.revoked_by = current_user.id
        overwritten_id = existing.id
        db.session.flush()

    rec = ScoreRecord(
        student_id=student_id, activity_name=activity,
        points=points, semester=semester,
        operator_id=current_user.id,
    )
    db.session.add(rec)
    db.session.flush()  # 拿到 id 用于审计
    if send_notify:
        db.session.add(Notification(
            student_id=student_id,
            content=(f"你新增加分：{activity} +{points} 分"
                     if not existing else
                     f"你的加分已更新：{activity} → {points} 分"),
        ))
    return ("overwritten" if existing else "added",
            f"+{points} 分", rec.id, overwritten_id)


@bp.route("/records/create", methods=["POST"])
@login_required
def records_create():
    """单人手动加分（弹窗提交）。"""
    sid = request.form.get("student_id", type=int)
    activity = (request.form.get("activity_name") or "").strip()
    points_raw = (request.form.get("points") or "").strip()
    semester = (request.form.get("semester") or current_semester()).strip()
    overwrite = bool(request.form.get("overwrite"))
    send_notify = bool(request.form.get("send_notify"))

    student = db.session.get(Student, sid) if sid else None
    if not student:
        flash("请选择学生", "warning")
        return redirect(request.referrer or url_for("admin.records"))
    if not activity:
        flash("活动名称不能为空", "warning")
        return redirect(request.referrer or url_for("admin.records"))
    points = _parse_points(points_raw)
    if points is None:
        flash(f"分值不合法：{points_raw}（需 0~99.99）", "warning")
        return redirect(request.referrer or url_for("admin.records"))

    status, msg, new_id, ow_id = _add_score_for(
        student.id, activity, points, semester, overwrite, send_notify=send_notify)
    if status == "duplicate":
        flash(f"{student.name}（{student.student_no}）本学期已有「{activity}」记录，{msg}。"
              f"若确需修改请勾选「覆盖已有记录」。", "warning")
        return redirect(request.referrer or url_for("admin.records"))

    audit_log("manual_add_record", target_type="score_record", target_id=new_id,
              student_id=student.id, student_no=student.student_no,
              activity=activity, points=str(points), semester=semester,
              mode=status, notify=send_notify,
              record_id=new_id, overwritten_id=ow_id)
    db.session.commit()
    notify_tail = "，已通知" if send_notify else "（未发通知）"
    flash(f"已为 {student.name}（{student.student_no}）加分 {activity} {msg}{notify_tail}",
          "success")
    return redirect(request.referrer or url_for("admin.records"))


@bp.route("/bulk_add", methods=["GET", "POST"])
@login_required
def bulk_add():
    """批量加分：一个活动一次性给多个学生。"""
    if request.method == "POST":
        activity = (request.form.get("activity_name") or "").strip()
        points_raw = (request.form.get("points") or "").strip()
        semester = (request.form.get("semester") or current_semester()).strip()
        overwrite = bool(request.form.get("overwrite"))
        send_notify = bool(request.form.get("send_notify"))
        student_ids = request.form.getlist("student_ids", type=int)

        errors = []
        if not activity:
            errors.append("活动名称不能为空")
        points = _parse_points(points_raw)
        if points is None:
            errors.append(f"分值不合法：{points_raw}（需 0~99.99）")
        if not student_ids:
            errors.append("请至少勾选一名学生")
        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for("admin.bulk_add"))

        added, overwritten, duplicated = 0, 0, 0
        dup_names = []
        new_ids: list[int] = []
        overwritten_ids: list[int] = []
        for sid in student_ids:
            student = db.session.get(Student, sid)
            if not student:
                continue
            status, _, nid, oid = _add_score_for(
                student.id, activity, points, semester, overwrite,
                send_notify=send_notify)
            if status == "added":
                added += 1
                if nid:
                    new_ids.append(nid)
            elif status == "overwritten":
                overwritten += 1
                if nid:
                    new_ids.append(nid)
                if oid:
                    overwritten_ids.append(oid)
            elif status == "duplicate":
                duplicated += 1
                dup_names.append(f"{student.name}({student.student_no})")

        audit_log("bulk_add_records", target_type="score_record",
                  activity=activity, points=str(points), semester=semester,
                  added=added, overwritten=overwritten, duplicated=duplicated,
                  notify=send_notify,
                  record_ids=new_ids, overwritten_ids=overwritten_ids)
        db.session.commit()

        msg = f"活动「{activity}」加分完成：新增 {added}"
        if overwritten:
            msg += f"，覆盖 {overwritten}"
        if duplicated:
            msg += (f"，跳过已有 {duplicated}"
                    f"（{', '.join(dup_names[:5])}"
                    f"{'…' if len(dup_names) > 5 else ''}）")
        msg += "，已通知学生" if send_notify else "（未发通知）"
        flash(msg + "。", "success")
        return redirect(url_for("admin.bulk_add"))

    students_all = Student.query.order_by(Student.student_no.asc()).all()
    return render_template("admin/bulk_add.html",
                           students=students_all,
                           current_sem=current_semester())


# ---------- 导出 / 备份 ----------

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
    items = Admin.query.order_by(Admin.is_super.desc(), Admin.created_at.asc()).all()
    return render_template("admin/admins.html", admins=items)


@bp.route("/admins/invite", methods=["POST"])
@login_required
@super_required
def admins_invite():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    is_super = bool(request.form.get("is_super"))
    if len(username) < 3 or len(password) < 8:
        flash("用户名至少 3 位，密码至少 8 位", "warning")
        return redirect(url_for("admin.admins_list"))
    if Admin.query.filter_by(username=username).first():
        flash("该用户名已存在", "warning")
        return redirect(url_for("admin.admins_list"))
    a = Admin(username=username, is_super=is_super)
    a.set_password(password)
    db.session.add(a)
    audit_log("invite_admin", target_type="admin", username=username, is_super=is_super)
    db.session.commit()
    flash(f"已添加管理员：{username}", "success")
    return redirect(url_for("admin.admins_list"))


@bp.route("/admins/<int:aid>/delete", methods=["POST"])
@login_required
@super_required
def admins_delete(aid: int):
    a = db.session.get(Admin, aid) or abort(404)
    if a.id == current_user.id:
        flash("不能删除自己", "danger")
        return redirect(url_for("admin.admins_list"))
    if a.is_super and Admin.query.filter_by(is_super=True).count() <= 1:
        flash("必须保留至少一个主管", "danger")
        return redirect(url_for("admin.admins_list"))
    audit_log("delete_admin", target_type="admin", target_id=a.id, username=a.username)
    db.session.delete(a)
    db.session.commit()
    flash("已删除", "success")
    return redirect(url_for("admin.admins_list"))


# ---------- 审计日志 ----------

@bp.route("/logs")
@login_required
def logs():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 50
    pagination = (AuditLog.query.order_by(AuditLog.created_at.desc())
                  .paginate(page=page, per_page=per_page, error_out=False))
    return render_template("admin/logs.html", pagination=pagination)


# ---------- 学期切换 ----------

@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        sem = (request.form.get("semester") or "").strip()
        if not sem:
            flash("学期标识不能为空", "warning")
        else:
            old = current_semester()
            Setting.set("current_semester", sem)
            audit_log("change_semester", before=old, after=sem)
            db.session.commit()
            flash(f"当前学期已切换为 {sem}", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html",
                           current_sem=current_semester(),
                           semesters=all_semesters())
