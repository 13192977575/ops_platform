"""schedules 后台管理。"""
from django.contrib import admin

from .models import ScheduleTask


@admin.register(ScheduleTask)
class ScheduleTaskAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "code",
        "script",
        "schedule_type",
        "cron_expr",
        "interval_seconds",
        "enabled",
        "concurrency_limit",
        "max_retries",
        "consecutive_failures",
        "last_run_at",
    ]
    list_filter = ["enabled", "schedule_type", "business", "environment"]
    search_fields = ["name", "code"]
    autocomplete_fields = ["script", "business", "project"]
