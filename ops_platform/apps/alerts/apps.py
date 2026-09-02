from django.apps import AppConfig


class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ops_platform.apps.alerts"
    label = "alerts"
    verbose_name = "监控告警"
