"""alerts 后台管理。"""
from django.contrib import admin

from .models import AlertChannel, AlertRecord, AlertRule


@admin.register(AlertChannel)
class AlertChannelAdmin(admin.ModelAdmin):
    list_display = ["name", "type", "enabled", "created_at"]
    list_filter = ["type", "enabled"]
    search_fields = ["name"]
    readonly_fields = ["config"]


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ["name", "asset_type", "asset_id", "metric", "threshold", "severity", "enabled", "silent_minutes"]
    list_filter = ["asset_type", "metric", "severity", "enabled", "business"]
    search_fields = ["name", "description"]
    filter_horizontal = ["channels"]
    autocomplete_fields = ["business"]


@admin.register(AlertRecord)
class AlertRecordAdmin(admin.ModelAdmin):
    list_display = ["id", "rule", "asset_type", "asset_id", "metric", "severity", "status", "acked_by", "created_at"]
    list_filter = ["status", "metric", "severity"]
    search_fields = ["message"]
    readonly_fields = ["rule", "asset_type", "asset_id", "metric", "severity", "message", "status", "channels", "send_result", "acked_by", "acked_at", "created_at"]
