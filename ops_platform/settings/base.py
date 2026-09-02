"""ops_platform 基础配置(dev / prod 共享)。

所有敏感配置一律通过环境变量注入,由 python-dotenv 从项目根 .env 加载;
禁止在代码中硬编码密钥、密码、连接串。
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录(含 manage.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 加载 .env(生产环境由容器/进程管理器注入环境变量,.env 仅作开发便捷)
load_dotenv(BASE_DIR / ".env")


def env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).lower() in ("1", "true", "yes", "on")


def env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, str(default)))


# ---------------------------------------------------------------------------
# 安全
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me-before-prod"
)
DEBUG = False  # 由子环境覆盖
ALLOWED_HOSTS: list[str] = []

# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "simpleui",  # 须在 admin 之前
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方
    "rest_framework",
    "django_filters",
    "django_celery_beat",
    "rest_framework_simplejwt.token_blacklist",
    # 平台业务 App
    "ops_platform.apps.common",
    "ops_platform.apps.accounts",
    "ops_platform.apps.audit",
    "ops_platform.apps.alerts",
    "ops_platform.apps.scripts",
    "ops_platform.apps.schedules",
    "ops_platform.apps.endpoints",
    "ops_platform.apps.executions",
    "ops_platform.apps.logs",
    "ops_platform.apps.executors",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ops_platform.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ops_platform.wsgi.application"
ASGI_APPLICATION = "ops_platform.asgi.application"

# ---------------------------------------------------------------------------
# 数据库(默认 SQLite,由子环境覆盖为 PostgreSQL)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# 自定义用户模型(accounts)
AUTH_USER_MODEL = "accounts.User"

# 密码校验
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# 告警(渠道凭据加密,密钥为 Fernet base64 urlsafe;生产必须显式设置)
# ---------------------------------------------------------------------------
ALERT_ENCRYPTION_KEY = os.environ.get("ALERT_ENCRYPTION_KEY", "")

# ---------------------------------------------------------------------------
# 国际化 / 时区
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Shanghai")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# SimpleUI(前端)
# ---------------------------------------------------------------------------
SIMPLEUI_HOME_PAGE = "/dashboard/"
SIMPLEUI_HOME_TITLE = "平台概览"
SIMPLEUI_HOME_ICON = "fa fa-tachometer"
SIMPLEUI_DEFAULT_THEME = "e-blue"
SIMPLEUI_ANALYSIS = False
SIMPLEUI_MENU = [
    {"name": "平台概览", "icon": "fa fa-tachometer", "url": "/dashboard/"},
    {"app": "accounts", "name": "用户与权限", "icon": "fa fa-users", "models": [
        {"name": "用户", "url": "/admin/accounts/user/", "icon": "fa fa-user"},
        {"name": "角色", "url": "/admin/accounts/role/", "icon": "fa fa-id-badge"},
        {"name": "数据范围", "url": "/admin/accounts/datascope/", "icon": "fa fa-shield"},
        {"name": "业务线", "url": "/admin/accounts/business/", "icon": "fa fa-building"},
        {"name": "项目", "url": "/admin/accounts/project/", "icon": "fa fa-folder-open"},
        {"name": "环境", "url": "/admin/accounts/environment/", "icon": "fa fa-globe"},
    ]},
    {"app": "scripts", "name": "脚本管理", "icon": "fa fa-code", "models": [
        {"name": "脚本", "url": "/admin/scripts/script/", "icon": "fa fa-file-code-o"},
        {"name": "脚本版本", "url": "/admin/scripts/scriptversion/", "icon": "fa fa-history"},
    ]},
    {"app": "schedules", "name": "定时任务", "icon": "fa fa-clock-o", "models": [
        {"name": "定时任务", "url": "/admin/schedules/scheduletask/", "icon": "fa fa-calendar"},
    ]},
    {"app": "endpoints", "name": "接口管理", "icon": "fa fa-plug", "models": [
        {"name": "接口", "url": "/admin/endpoints/httpendpoint/", "icon": "fa fa-link"},
        {"name": "调用记录", "url": "/admin/endpoints/endpointcalllog/", "icon": "fa fa-list-alt"},
    ]},
    {"app": "executions", "name": "执行中心", "icon": "fa fa-play-circle", "models": [
        {"name": "执行记录", "url": "/admin/executions/execution/", "icon": "fa fa-tasks"},
    ]},
    {"app": "logs", "name": "日志中心", "icon": "fa fa-file-text", "models": [
        {"name": "执行日志", "url": "/admin/logs/logentry/", "icon": "fa fa-file-text-o"},
    ]},
    {"app": "audit", "name": "审计日志", "icon": "fa fa-history", "models": [
        {"name": "审计日志", "url": "/admin/audit/auditlog/", "icon": "fa fa-balance-scale"},
    ]},
    {"app": "alerts", "name": "监控告警", "icon": "fa fa-bell", "models": [
        {"name": "告警渠道", "url": "/admin/alerts/alertchannel/", "icon": "fa fa-paper-plane"},
        {"name": "告警规则", "url": "/admin/alerts/alertrule/", "icon": "fa fa-sliders"},
        {"name": "告警记录", "url": "/admin/alerts/alertrecord/", "icon": "fa fa-bell-o"},
    ]},
]

# ---------------------------------------------------------------------------
# 静态与媒体
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "MAX_PAGE_SIZE": 200,
    "DATETIME_FORMAT": "%Y-%m-%d %H:%M:%S",
}

# ---------------------------------------------------------------------------
# SimpleJWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MINUTES", 30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ---------------------------------------------------------------------------
# Celery(Redis 作为 broker / result backend;django-celery-beat 落库调度)
# ---------------------------------------------------------------------------
_REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = _REDIS_URL
CELERY_RESULT_BACKEND = _REDIS_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env_int("CELERY_TASK_TIME_LIMIT", 1800)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ---------------------------------------------------------------------------
# 日志(统一 JSON 格式;执行日志中心见 P5 的 logs app,此处为基础框架日志)
# ---------------------------------------------------------------------------
# 日志保留天数:清理任务定期删除更早的执行日志
LOG_RETENTION_DAYS = env_int("LOG_RETENTION_DAYS", 90)

# 确保文件日志目录存在(django.setup() 配置 LOGGING 时不会自动创建)
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
        "verbose": {
            "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "ops.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "json",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
    },
}
