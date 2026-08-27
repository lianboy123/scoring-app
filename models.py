"""数据模型。

核心表：学生、管理员、加分记录、申报、分配规则、通知和设置。
"""
from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import Index
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class Student(db.Model):
    __tablename__ = "student"

    id = db.Column(db.Integer, primary_key=True)
    student_no = db.Column(db.String(32), unique=True, nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    score_records = db.relationship("ScoreRecord", back_populates="student", lazy="dynamic")
    notifications = db.relationship("Notification", back_populates="student", lazy="dynamic")

    def __repr__(self):
        return f"<Student {self.student_no} {self.name}>"


class Admin(db.Model, UserMixin):
    __tablename__ = "admin"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_super = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password, method="pbkdf2:sha256")

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self):
        return f"<Admin {self.username}{' *' if self.is_super else ''}>"


class UploadBatch(db.Model):
    __tablename__ = "upload_batch"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255))
    uploader_id = db.Column(db.Integer, db.ForeignKey("admin.id"))
    semester = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending / approved / rolled_back
    total_rows = db.Column(db.Integer, default=0)
    approved_rows = db.Column(db.Integer, default=0)
    parsed_json = db.Column(db.Text)  # 预览阶段缓存的解析结果（JSON）
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploader = db.relationship("Admin", foreign_keys=[uploader_id])
    records = db.relationship("ScoreRecord", back_populates="batch", lazy="dynamic")


class ScoreRecord(db.Model):
    __tablename__ = "score_record"
    # 部分唯一索引：只对 is_revoked=0 的记录限制重复，
    # 这样允许"覆盖"场景下旧记录被软删除、同 key 新行可以插入。
    __table_args__ = (
        Index(
            "uq_student_activity_semester_active",
            "student_id", "activity_name", "semester",
            unique=True,
            sqlite_where=db.text("is_revoked = 0"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    activity_name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(32), nullable=False, default="behavior", index=True)
    is_public = db.Column(db.Boolean, default=True, nullable=False, index=True)
    points = db.Column(db.Numeric(5, 2), nullable=False)
    semester = db.Column(db.String(32), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("upload_batch.id"))
    operator_id = db.Column(db.Integer, db.ForeignKey("admin.id"))
    is_revoked = db.Column(db.Boolean, default=False, nullable=False, index=True)
    revoked_at = db.Column(db.DateTime)
    revoked_by = db.Column(db.Integer, db.ForeignKey("admin.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student", back_populates="score_records")
    batch = db.relationship("UploadBatch", back_populates="records")
    operator = db.relationship("Admin", foreign_keys=[operator_id])
    revoker = db.relationship("Admin", foreign_keys=[revoked_by])


class Notification(db.Model):
    __tablename__ = "notification"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student", back_populates="notifications")


class Claim(db.Model):
    """学生对除行为规范外的类别进行加分申报。"""
    __tablename__ = "claim"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    category = db.Column(db.String(32), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False)
    semester = db.Column(db.String(32), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey("admin.id"), index=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("admin.id"))
    awarded_points = db.Column(db.Numeric(5, 2))
    review_note = db.Column(db.String(500))
    score_record_id = db.Column(db.Integer, db.ForeignKey("score_record.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    reviewed_at = db.Column(db.DateTime)

    student = db.relationship("Student")
    assigned_admin = db.relationship("Admin", foreign_keys=[assigned_admin_id])
    reviewer = db.relationship("Admin", foreign_keys=[reviewer_id])
    score_record = db.relationship("ScoreRecord")


class AssignmentRule(db.Model):
    """按学号字符串区间分配申报审核员。"""
    __tablename__ = "assignment_rule"

    id = db.Column(db.Integer, primary_key=True)
    start_no = db.Column(db.String(32), nullable=False)
    end_no = db.Column(db.String(32), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("admin.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    admin = db.relationship("Admin")


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admin.id"))
    action = db.Column(db.String(64), nullable=False)
    target_type = db.Column(db.String(64))
    target_id = db.Column(db.Integer)
    detail = db.Column(db.Text)  # JSON 字符串
    is_undone = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    admin = db.relationship("Admin")


class Setting(db.Model):
    __tablename__ = "setting"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text)

    @classmethod
    def get(cls, key: str, default=None):
        item = db.session.get(cls, key)
        return item.value if item else default

    @classmethod
    def set(cls, key: str, value: str) -> None:
        item = db.session.get(cls, key)
        if item:
            item.value = value
        else:
            item = cls(key=key, value=value)
            db.session.add(item)
