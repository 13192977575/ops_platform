"""定时任务调度入口:由 django-celery-beat 触发的周期性任务。

职责:
1. 检查任务启用状态;
2. 并发控制:select_for_update 锁定任务行,统计正在执行的实例数,
   达到 concurrency_limit 则跳过本次触发;
3. 创建 Execution(SCHEDULE 类型,pending)并投递 execute_asset 执行。
"""
from __future__ import annotations

import uuid

from celery import shared_task
from django.db import transaction

from ops_platform.apps.executions.models import Execution
from ops_platform.apps.executions.tasks import execute_asset

from .models import ScheduleTask


@shared_task(name="schedules.run_schedule")
def run_schedule(schedule_id: int) -> dict:
    schedule = ScheduleTask.objects.get(pk=schedule_id)
    if not schedule.enabled:
        return {"schedule_id": schedule_id, "skipped": True, "reason": "disabled"}

    with transaction.atomic():
        locked = ScheduleTask.objects.select_for_update().get(pk=schedule_id)
        running = Execution.objects.filter(
            asset_type=Execution.AssetType.SCHEDULE,
            asset_id=schedule_id,
            status__in=[Execution.Status.RUNNING, Execution.Status.RETRYING],
        ).count()
        if running >= locked.concurrency_limit:
            return {
                "schedule_id": schedule_id,
                "skipped": True,
                "reason": "concurrency_limit",
                "running": running,
            }
        execution = Execution.objects.create(
            asset_type=Execution.AssetType.SCHEDULE,
            asset_id=schedule_id,
            trigger_type=Execution.TriggerType.SCHEDULE,
            params=locked.params or {},
            request_id=str(uuid.uuid4()),
            business=locked.business,
            project=locked.project,
            environment=locked.environment,
        )

    execute_asset.delay(execution.pk)
    return {"schedule_id": schedule_id, "execution_id": execution.pk}
