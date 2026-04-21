"""导出 Excel。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import func

from extensions import db
from models import ScoreRecord, Student


HEADER_FILL = PatternFill("solid", fgColor="7C3AED")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def export_records_xlsx(semester: str) -> tuple[BytesIO, str]:
    """导出某学期所有有效加分记录 + 一张汇总表。"""
    wb = Workbook()

    # Sheet 1: 明细
    ws = wb.active
    ws.title = "加分明细"
    headers = ["学号", "姓名", "活动名称", "分值", "学期", "录入时间"]
    ws.append(headers)
    for c in ws[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="center")

    rows = (db.session.query(ScoreRecord, Student)
            .join(Student, Student.id == ScoreRecord.student_id)
            .filter(ScoreRecord.semester == semester,
                    ScoreRecord.is_revoked.is_(False))
            .order_by(Student.student_no.asc(), ScoreRecord.created_at.asc())
            .all())
    for rec, st in rows:
        ws.append([
            st.student_no, st.name, rec.activity_name,
            float(rec.points), rec.semester,
            rec.created_at.strftime("%Y-%m-%d %H:%M") if rec.created_at else "",
        ])
    for i, w in enumerate([16, 14, 32, 10, 14, 18], start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    # Sheet 2: 汇总（按学生）
    ws2 = wb.create_sheet("学期汇总")
    ws2.append(["学号", "姓名", "总分", "记录数"])
    for c in ws2[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="center")

    summary = (db.session.query(
                    Student.student_no, Student.name,
                    func.coalesce(func.sum(ScoreRecord.points), 0).label("total"),
                    func.count(ScoreRecord.id).label("cnt"))
               .outerjoin(ScoreRecord,
                          (ScoreRecord.student_id == Student.id)
                          & (ScoreRecord.semester == semester)
                          & (ScoreRecord.is_revoked.is_(False)))
               .group_by(Student.id)
               .order_by(func.coalesce(func.sum(ScoreRecord.points), 0).desc(),
                         Student.student_no.asc())
               .all())
    for no, name, total, cnt in summary:
        ws2.append([no, name, float(total or 0), int(cnt or 0)])
    for i, w in enumerate([16, 14, 10, 10], start=1):
        ws2.column_dimensions[chr(64 + i)].width = w

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = f"加分汇总-{semester}-{datetime.now().strftime('%Y%m%d%H%M')}.xlsx"
    return bio, filename
