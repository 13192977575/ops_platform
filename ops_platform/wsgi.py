"""WSGI 入口(gunicorn 使用)。"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ops_platform.settings")

application = get_wsgi_application()

# 确保配置好的 Celery 应用在本进程加载并设为 current:
# gunicorn 不经过 manage.py/celery 命令行,若不显式导入,shared_task 绑定的
# 默认 app 未配置 broker,delay() 会去连默认 amqp 导致 Connection refused。
from ops_platform.celery import app as celery_app  # noqa: E402,F401

celery_app.set_current()
