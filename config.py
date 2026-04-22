"""应用配置。

通过环境变量 SCORING_ENV=prod 切换为生产配置。
"""
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


class BaseConfig:
    SECRET_KEY = os.environ.get("SCORING_SECRET_KEY", "dev-secret-change-me")

    SQLALCHEMY_DATABASE_URI = f"sqlite:///{INSTANCE_DIR / 'scoring.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 2  # 管理员 2 小时

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 单次上传 ≤ 16MB（学生名单 / 加分 Excel 足够）

    DEFAULT_SEMESTER = os.environ.get("SCORING_DEFAULT_SEMESTER", "2026-spring")


class DevConfig(BaseConfig):
    DEBUG = True


class ProdConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


def get_config():
    env = os.environ.get("SCORING_ENV", "dev").lower()
    return ProdConfig if env == "prod" else DevConfig
