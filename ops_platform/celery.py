"""Celery 应用:broker / result 使用 Redis,Beat 使用数据库调度器。

注意:worker/beat 是独立进程(不走 manage.py),必须先 django.setup()
初始化 settings 与 app 注册表,否则 config_from_object 与任务导入会失败。
"""
import os

import django
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ops_platform.settings")

django.setup()

app = Celery("ops_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
