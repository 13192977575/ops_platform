"""audit 后台管理。"""
from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["id", "actor", "action", "target_type", "target_id", "ip", "created_at"]
    list_filter = ["action", "target_type"]
    search_fields = ["action", "target_type", "target_id"]
    readonly_fields = ["actor", "action", "target_type", "target_id", "detail", "ip", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
