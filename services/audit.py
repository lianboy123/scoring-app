"""审计日志辅助。"""
import json
from typing import Any, Optional

from flask_login import current_user

from extensions import db
from models import AuditLog


def log(action: str, target_type: Optional[str] = None,
        target_id: Optional[int] = None, **detail: Any) -> None:
    """记录一条审计日志。

    在请求上下文中自动取 current_user.id，否则 admin_id 留空。
    detail 以 JSON 字符串保存。
    """
    admin_id = None
    try:
        if current_user.is_authenticated:
            admin_id = current_user.id
    except Exception:
        pass

    entry = AuditLog(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    db.session.add(entry)
