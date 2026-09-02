"""日志保留清理任务:按保留天数删除过期执行日志,由每日 PeriodicTask 触发。"""
from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import LogEntry


@shared_task(name="logs.clean_old_logs")
def clean_old_logs(days: int | None = None) -> dict:
    days = days if days is not None else getattr(settings, "LOG_RETENTION_DAYS", 90)
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = LogEntry.objects.filter(created_at__lt=cutoff).delete()
    return {"deleted": deleted, "days": days, "cutoff": cutoff.isoformat()}
