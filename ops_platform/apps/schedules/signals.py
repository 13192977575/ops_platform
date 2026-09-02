"""ScheduleTask ↔ django-celery-beat PeriodicTask 同步信号。

- 创建/更新:按 schedule_type 解析 cron/interval,get_or_create 调度实体,
  任务指向 schedules.run_schedule,kwargs 携带 schedule_id;enabled 同步;
- 停用:仅置 PeriodicTask.enabled=False(保留调度实体,便于再次启用);
- 删除:级联删除对应 PeriodicTask。
"""
from __future__ import annotations

import json

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from .cron import parse_cron
from .models import ScheduleTask


def sync_periodic_task(instance: ScheduleTask) -> None:
    """按 ScheduleTask 当前状态同步 PeriodicTask;无启用需求或表达式非法时跳过。

    注意:始终直接查询 DB 获取关联 PeriodicTask,不使用 instance.periodic_task
    (创建时回写外键用的是 queryset.update,实例上的反向属性会缓存 None)。
    """
    pt = PeriodicTask.objects.filter(schedule_task=instance).first()

    if not instance.enabled:
        if pt is not None and pt.enabled:
            pt.enabled = False
            pt.save(update_fields=["enabled"])
        return

    crontab = None
    interval = None
    if instance.schedule_type == ScheduleTask.ScheduleType.CRON:
        try:
            fields = parse_cron(instance.cron_expr)
        except ValueError:
            return  # 非法表达式由 serializer 校验拦截,此处兜底跳过
        crontab, _ = CrontabSchedule.objects.get_or_create(
            timezone=instance.timezone, **fields
        )
    elif instance.schedule_type == ScheduleTask.ScheduleType.INTERVAL:
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=instance.interval_seconds, period=IntervalSchedule.SECONDS
        )
    else:
        return

    expected_name = f"schedule-{instance.code}"
    if pt is None:
        pt = PeriodicTask.objects.create(
            name=expected_name,
            task="schedules.run_schedule",
            crontab=crontab,
            interval=interval,
            args=json.dumps([]),
            kwargs=json.dumps({"schedule_id": instance.pk}),
            enabled=True,
        )
        # 回写外键并同步实例内存属性(queryset.update 不会更新实例;
        # post_delete 依赖 periodic_task_id 直删 PeriodicTask)
        ScheduleTask.objects.filter(pk=instance.pk).update(periodic_task=pt)
        instance.periodic_task_id = pt.pk
        return

    changed = False
    if pt.crontab_id != (crontab.pk if crontab else None) or pt.interval_id != (
        interval.pk if interval else None
    ):
        pt.crontab = crontab
        pt.interval = interval
        changed = True
    if not pt.enabled:
        pt.enabled = True
        changed = True
    if pt.name != expected_name:
        pt.name = expected_name
        changed = True
    if changed:
        pt.save()


@receiver(post_save, sender=ScheduleTask)
def _on_schedule_saved(sender, instance, **kwargs):
    sync_periodic_task(instance)


@receiver(post_delete, sender=ScheduleTask)
def _on_schedule_deleted(sender, instance, **kwargs):
    # 行已删除,不能再用反向关系查询(需 JOIN 已删行);直接用内存中的外键主键删除
    periodic_task_id = instance.periodic_task_id
    if periodic_task_id is not None:
        PeriodicTask.objects.filter(pk=periodic_task_id).delete()
