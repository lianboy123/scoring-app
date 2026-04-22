"""Flask 应用工厂。"""
from flask import Flask, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config
from extensions import db, login_manager


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(get_config())
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    login_manager.init_app(app)

    from models import Admin

    @login_manager.user_loader
    def load_admin(user_id: str):
        return db.session.get(Admin, int(user_id))

    from blueprints.install import bp as install_bp
    from blueprints.student import bp as student_bp
    from blueprints.admin import bp as admin_bp

    app.register_blueprint(install_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(admin_bp)

    @app.before_request
    def _ensure_first_install():
        from flask import request

        if request.endpoint in (None, "static"):
            return None
        if request.endpoint and request.endpoint.startswith("install."):
            return None

        if db.session.query(Admin.id).first() is None:
            return redirect(url_for("install.install"))
        return None

    with app.app_context():
        db.create_all()
        _auto_migrate()

    return app


def _auto_migrate() -> None:
    """轻量迁移：给已有 DB 按需补上新增列。
    SQLite 专用：create_all 不会改已存在表，这里用 PRAGMA 检查并 ALTER。
    """
    from sqlalchemy import text

    def ensure_column(table: str, col: str, col_def: str) -> None:
        rows = db.session.execute(text(f"PRAGMA table_info({table})")).all()
        existing = {r[1] for r in rows}
        if col not in existing:
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
            db.session.commit()

    try:
        ensure_column("audit_log", "is_undone", "BOOLEAN NOT NULL DEFAULT 0")
    except Exception:
        db.session.rollback()


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
