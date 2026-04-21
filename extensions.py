"""Flask 扩展单例。"""
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "admin.login"
login_manager.login_message = "请先登录管理员账号"
login_manager.login_message_category = "warning"
