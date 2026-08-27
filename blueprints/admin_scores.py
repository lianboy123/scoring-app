"""管理员端：文件审核与加分记录管理。"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Notification, ScoreRecord, Student, UploadBatch
from services.audit import log as audit_log
from services.semesters import current_semester

from blueprints.admin import bp

@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        flash("文件自动识别功能正在规划中，当前请使用行为规范批量录入。", "warning")
        return redirect(url_for("admin.bulk_add"))
    return render_template("admin/upload_pending.html")


@bp.route("/manage/<category>")
@login_required
def category_page(category: str):
    from blueprints.admin import SCORING_CATEGORIES
    item = next((item for item in SCORING_CATEGORIES if item["slug"] == category), None)
    if not item:
        abort(404)
    if item["slug"] == "behavior":
        return redirect(url_for("admin.bulk_add"))
    return redirect(url_for("admin.claims", category=item["slug"]))


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
    rows = (query.order_by(ScoreRecord.activity_name.asc(),
                           Student.student_no.asc()).limit(1000).all())
    activity_groups = []
    for rec, student in rows:
        if not activity_groups or activity_groups[-1]["name"] != rec.activity_name:
            activity_groups.append({"name": rec.activity_name, "rows": [], "total": Decimal("0")})
        activity_groups[-1]["rows"].append((rec, student))
        if not rec.is_revoked:
            activity_groups[-1]["total"] += rec.points
    students_all = Student.query.order_by(Student.student_no.asc()).all()
    return render_template("admin/records.html",
                           rows=rows, activity_groups=activity_groups,
                           sem=sem, q=q, show_revoked=show_revoked,
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
    if p < Decimal("-99.99") or p > Decimal("99.99"):
        return None
    return p


def _add_score_for(student_id: int, activity: str, points: Decimal,
                   semester: str, overwrite: bool,
                   send_notify: bool = True,
                   is_public: bool = True) -> tuple[str, str, int | None, int | None]:
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
        points=points, semester=semester, category="behavior",
        is_public=is_public,
        operator_id=current_user.id,
    )
    db.session.add(rec)
    db.session.flush()  # 拿到 id 用于审计
    if send_notify:
        db.session.add(Notification(
            student_id=student_id,
            content=(f"你的行为规范分已更新：{activity} {points:+} 分"
                     if not existing else
                     f"你的加分已更新：{activity} → {points} 分"),
        ))
    return ("overwritten" if existing else "added",
            f"{points:+} 分", rec.id, overwritten_id)


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
    is_public = bool(request.form.get("is_public"))

    student = db.session.get(Student, sid) if sid else None
    if not student:
        flash("请选择学生", "warning")
        return redirect(request.referrer or url_for("admin.records"))
    if not activity:
        flash("活动名称不能为空", "warning")
        return redirect(request.referrer or url_for("admin.records"))
    points = _parse_points(points_raw)
    if points is None:
        flash(f"分值不合法：{points_raw}（需 -99.99~99.99）", "warning")
        return redirect(request.referrer or url_for("admin.records"))

    status, msg, new_id, ow_id = _add_score_for(
        student.id, activity, points, semester, overwrite,
        send_notify=send_notify, is_public=is_public)
    if status == "duplicate":
        flash(f"{student.name}（{student.student_no}）本学期已有「{activity}」记录，{msg}。"
              f"若确需修改请勾选「覆盖已有记录」。", "warning")
        return redirect(request.referrer or url_for("admin.records"))

    audit_log("manual_add_record", target_type="score_record", target_id=new_id,
              student_id=student.id, student_no=student.student_no,
              activity=activity, points=str(points), semester=semester,
              mode=status, notify=send_notify, is_public=is_public,
              record_id=new_id, overwritten_id=ow_id)
    db.session.commit()
    notify_tail = "，已通知" if send_notify else "（未发通知）"
    flash(f"已为 {student.name}（{student.student_no}）加分 {activity} {msg}{notify_tail}",
          "success")
    return redirect(request.referrer or url_for("admin.records"))


@bp.route("/bulk_add", methods=["GET", "POST"])
@login_required
def bulk_add():
    """行为规范批量录入：一个活动中每位学生可有不同分值。"""
    if request.method == "POST":
        activity = (request.form.get("activity_name") or "").strip()
        semester = (request.form.get("semester") or current_semester()).strip()
        overwrite = bool(request.form.get("overwrite"))
        send_notify = bool(request.form.get("send_notify"))
        is_public = bool(request.form.get("is_public"))
        student_ids = request.form.getlist("student_ids", type=int)

        errors = []
        if not activity:
            errors.append("活动名称不能为空")
        if not student_ids:
            errors.append("请至少勾选一名学生")
        points_by_student: dict[int, Decimal] = {}
        for sid in student_ids:
            raw = (request.form.get(f"points_{sid}") or "").strip()
            points = _parse_points(raw)
            if points is None:
                student = db.session.get(Student, sid)
                who = f"{student.name}（{student.student_no}）" if student else str(sid)
                errors.append(f"{who} 的分值不合法（需 -99.99~99.99）")
            else:
                points_by_student[sid] = points
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
            student_points = points_by_student[student.id]
            status, _, nid, oid = _add_score_for(
                student.id, activity, student_points, semester, overwrite,
                send_notify=send_notify, is_public=is_public)
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
                  activity=activity,
                  points_by_student={str(k): str(v) for k, v in points_by_student.items()},
                  semester=semester,
                  added=added, overwritten=overwritten, duplicated=duplicated,
                  notify=send_notify, is_public=is_public,
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
