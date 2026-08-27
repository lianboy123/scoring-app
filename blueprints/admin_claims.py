"""管理员端：学生加分申报审核。"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Claim, Notification, ScoreRecord, Student
from services.audit import log as audit_log
from services.categories import CATEGORY_MAP, CLAIMABLE_CATEGORIES

from blueprints.admin import bp


def _visible_claim(claim_id: int) -> Claim:
    claim = db.session.get(Claim, claim_id) or abort(404)
    if not current_user.is_super and claim.assigned_admin_id != current_user.id:
        abort(403)
    return claim


@bp.route("/claims")
@login_required
def claims():
    status = request.args.get("status") or "pending"
    category = (request.args.get("category") or "").strip()
    valid_categories = {item["slug"] for item in CLAIMABLE_CATEGORIES}
    if category and category not in valid_categories:
        abort(404)
    query = Claim.query
    if not current_user.is_super:
        query = query.filter(Claim.assigned_admin_id == current_user.id)
    if status in {"pending", "approved", "rejected"}:
        query = query.filter(Claim.status == status)
    if category:
        query = query.filter(Claim.category == category)
    items = query.order_by(Claim.created_at.desc()).all()
    return render_template("admin/claims.html", claims=items, status=status,
                           category=category,
                           category_label=CATEGORY_MAP.get(category, "全部申报"),
                           category_map=CATEGORY_MAP)


@bp.route("/claims/<int:claim_id>/review", methods=["POST"])
@login_required
def claim_review(claim_id: int):
    claim = _visible_claim(claim_id)
    if claim.status != "pending":
        flash("该申报已处理", "warning")
        return redirect(url_for("admin.claims", category=claim.category))
    action = request.form.get("action")
    note = (request.form.get("review_note") or "").strip()[:500]
    if action == "reject":
        claim.status = "rejected"
        claim.reviewer_id = current_user.id
        claim.review_note = note
        claim.reviewed_at = datetime.utcnow()
        db.session.add(Notification(
            student_id=claim.student_id,
            content=f"你的申报「{claim.title}」未通过审核"
                    + (f"：{note}" if note else "。"),
        ))
        audit_log("reject_claim", target_type="claim", target_id=claim.id,
                  note=note)
        db.session.commit()
        flash("已驳回申报并通知学生", "success")
        return redirect(url_for("admin.claims", category=claim.category))

    try:
        points = Decimal((request.form.get("points") or "").strip())
    except (InvalidOperation, ValueError):
        points = Decimal("0")
    if points <= 0 or points > Decimal("99.99"):
        flash("通过申报时，加分必须在 0.01~99.99 之间", "warning")
        return redirect(url_for("admin.claims", category=claim.category))

    activity_name = claim.title
    conflict = ScoreRecord.query.filter_by(
        student_id=claim.student_id, activity_name=activity_name,
        semester=claim.semester, is_revoked=False,
    ).first()
    if conflict:
        activity_name = f"{claim.title}（申报{claim.id}）"
    record = ScoreRecord(
        student_id=claim.student_id, activity_name=activity_name,
        category=claim.category, points=points, semester=claim.semester,
        is_public=bool(request.form.get("is_public")),
        operator_id=current_user.id,
    )
    db.session.add(record)
    db.session.flush()
    claim.status = "approved"
    claim.reviewer_id = current_user.id
    claim.review_note = note
    claim.awarded_points = points
    claim.score_record_id = record.id
    claim.reviewed_at = datetime.utcnow()
    db.session.add(Notification(
        student_id=claim.student_id,
        content=f"你的申报「{claim.title}」已通过，"
                f"{CATEGORY_MAP.get(claim.category, claim.category)} +{points} 分。",
    ))
    audit_log("approve_claim", target_type="claim", target_id=claim.id,
              points=str(points), category=claim.category, record_id=record.id,
              is_public=record.is_public)
    db.session.commit()
    flash("已通过申报、记入加分并通知学生", "success")
    return redirect(url_for("admin.claims", category=claim.category))
