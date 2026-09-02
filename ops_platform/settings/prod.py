"""生产环境配置:PostgreSQL,强制敏感配置来自环境变量,缺失即启动失败。"""
import os

from .base import *  # noqa: F401,F403
from .base import env_bool, env_int

DEBUG = False

_allowed = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
if not _allowed:
    raise RuntimeError("生产环境必须设置 DJANGO_ALLOWED_HOSTS")
if "*" in [h.strip() for h in _allowed.split(",")]:
    raise RuntimeError("生产环境禁止使用 ALLOWED_HOSTS 通配符,请显式指定域名")
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()]

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

if not os.environ.get("ALERT_ENCRYPTION_KEY"):
    raise RuntimeError("生产环境必须设置 ALERT_ENCRYPTION_KEY(Fernet 密钥)")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env_bool("POSTGRES_CONN_MAX_AGE", True) and 60 or 0,
    }
}

# 生产默认关闭的调试项
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
