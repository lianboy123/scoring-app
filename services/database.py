"""数据库初始化和轻量兼容迁移。"""
from sqlalchemy import text

from extensions import db


def initialize_database() -> None:
    """创建缺失表，并为旧版 SQLite 数据库补齐新增字段。"""
    db.create_all()
    migrations = [
        ("audit_log", "is_undone", "BOOLEAN NOT NULL DEFAULT 0"),
        ("score_record", "category", "VARCHAR(32) NOT NULL DEFAULT 'behavior'"),
        ("score_record", "is_public", "BOOLEAN NOT NULL DEFAULT 1"),
    ]
    for table, column, definition in migrations:
        try:
            _ensure_column(table, column, definition)
        except Exception:
            # 单个兼容迁移失败不阻止网站启动。
            db.session.rollback()


def _ensure_column(table: str, column: str, definition: str) -> None:
    rows = db.session.execute(text(f"PRAGMA table_info({table})")).all()
    existing = {row[1] for row in rows}
    if column in existing:
        return

    db.session.execute(
        text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    )
    db.session.commit()
