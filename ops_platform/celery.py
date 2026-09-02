"""Celery 应用:broker / result 使用 Redis,Beat 使用数据库调度器。

worker/beat 是独立进程(不走 manage.py),需在 import 模型前初始化 Django;
但 manage.py / gunicorn 启动时 populate 过程中会 import 本模块,
此时必须跳过 setup,避免 "populate() isn't reentrant"。
"""
import os

import django
from celery import Celery
from django.apps import apps

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ops_platform.settings")

# 仅在 Django 未初始化且不在 populate 进行中时执行 setup
if not apps.loading and not apps.ready:
    django.setup()

app = Celery("ops_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
