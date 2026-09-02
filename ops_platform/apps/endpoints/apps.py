from django.apps import AppConfig


class EndpointsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ops_platform.apps.endpoints"
    label = "endpoints"
    verbose_name = "接口管理"

    def ready(self):
        # 确保 monitor 巡检的 PeriodicTask 存在(在 migrate 完成后注册,幂等)
        from django.db.models.signals import post_migrate

        post_migrate.connect(self._ensure_monitor_task, sender=self)

    def _ensure_monitor_task(self, **kwargs):
        import json

        from django_celery_beat.models import IntervalSchedule, PeriodicTask

        interval, _ = IntervalSchedule.objects.get_or_create(
            every=60, period=IntervalSchedule.SECONDS
        )
        PeriodicTask.objects.get_or_create(
            name="monitor-endpoints",
            defaults={
                "task": "endpoints.monitor_endpoints",
                "interval": interval,
                "args": json.dumps([]),
                "kwargs": json.dumps({}),
                "enabled": True,
            },
        )
