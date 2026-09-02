"""ASGI 入口。"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ops_platform.settings")

application = get_asgi_application()

# 与 wsgi.py 同理:确保配置好的 Celery 应用在进程内设为 current
# (见 wsgi.py 注释,防止 shared_task 绑定未配置 broker 的默认 app)
from ops_platform.celery import app as celery_app  # noqa: E402,F401

celery_app.set_current()
