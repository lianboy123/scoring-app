"""Flask 应用工厂。"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import Flask, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config
from extensions import db, login_manager
from services.database import initialize_database


def create_app(config_overrides: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(get_config())
    if config_overrides:
        app.config.update(config_overrides)
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
        initialize_database()

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5050, debug=True)
