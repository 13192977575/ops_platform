from django.apps import AppConfig


class ScriptsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ops_platform.apps.scripts"
    label = "scripts"
    verbose_name = "脚本管理"
