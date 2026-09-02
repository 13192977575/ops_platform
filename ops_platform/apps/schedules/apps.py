from django.apps import AppConfig


class SchedulesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ops_platform.apps.schedules"
    label = "schedules"
    verbose_name = "定时任务"

    def ready(self):
        from . import signals  # noqa: F401
