"""管理员端：学生名单管理。"""
from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required

from extensions import db
from models import ScoreRecord, Student
from services.audit import log as audit_log
from services.parser import ParseError, parse_roster

from blueprints.admin import bp

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


@bp.route("/students/export")
@login_required
def students_export():
    from services.exporter import export_roster_xlsx
    from services.semesters import current_semester
    bio, filename = export_roster_xlsx(current_semester())
    return send_file(
        bio, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


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
