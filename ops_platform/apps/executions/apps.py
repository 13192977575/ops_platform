from django.apps import AppConfig


class ExecutionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ops_platform.apps.executions"
    label = "executions"
    verbose_name = "执行记录"
