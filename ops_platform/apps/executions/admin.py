"""executions / logs 后台管理。"""
from django.contrib import admin

from ops_platform.apps.logs.models import LogEntry

from .models import Execution


class LogEntryInline(admin.TabularInline):
    model = LogEntry
    extra = 0
    readonly_fields = ["created_at"]
    can_delete = False


@admin.register(Execution)
class ExecutionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "asset_type",
        "asset_id",
        "trigger_type",
        "trigger_user",
        "status",
        "request_id",
        "node",
        "duration_ms",
        "created_at",
    ]
    list_filter = ["asset_type", "trigger_type", "status", "business", "environment"]
    search_fields = ["request_id", "error_message"]
    inlines = [LogEntryInline]


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ["id", "execution", "level", "user", "node", "message", "created_at"]
    list_filter = ["level"]
    search_fields = ["message", "request_id"]
