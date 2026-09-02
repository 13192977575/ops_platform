from django.apps import AppConfig


class LogsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ops_platform.apps.logs"
    label = "logs"
    verbose_name = "日志中心"

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(self._ensure_clean_task, sender=self)

    def _ensure_clean_task(self, **kwargs):
        from django.conf import settings

        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute="0",
            hour="3",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone=settings.TIME_ZONE,
        )
        PeriodicTask.objects.get_or_create(
            name="clean-old-logs",
            defaults={
                "task": "logs.clean_old_logs",
                "crontab": crontab,
                "enabled": True,
            },
        )
