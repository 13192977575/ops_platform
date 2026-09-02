"""开发环境配置:DEBUG 开启,SQLite 数据库,无敏感默认值要求。"""
import os

from .base import *  # noqa: F401,F403
from .base import BASE_DIR

DEBUG = True
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# 开发环境允许跨域等调试便利(生产环境务必收紧)
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
).split(",")

# 告警渠道凭据加密密钥(dev 固定默认,仅用于开发;生产见 prod.py 强制要求)
ALERT_ENCRYPTION_KEY = os.environ.get(
    "ALERT_ENCRYPTION_KEY", "EgaGWm1_k-nRv8C7s5wkPGHqIpB8rDbUmGwy7GLA6no="
)
