"""endpoints 后台管理。"""
from django.contrib import admin

from .models import EndpointCallLog, HttpEndpoint


class EndpointCallLogInline(admin.TabularInline):
    model = EndpointCallLog
    extra = 0
    readonly_fields = ["created_at"]
    can_delete = False


@admin.register(HttpEndpoint)
class HttpEndpointAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "code",
        "mode",
        "status",
        "auth_type",
        "health_status",
        "call_count",
        "error_rate",
        "avg_response_ms",
        "last_check_at",
    ]
    list_filter = ["mode", "status", "auth_type", "health_status", "business", "environment"]
    search_fields = ["name", "code", "url"]
    autocomplete_fields = ["script", "business", "project"]
    inlines = [EndpointCallLogInline]
    readonly_fields = ["auth_key_hash"]


@admin.register(EndpointCallLog)
class EndpointCallLogAdmin(admin.ModelAdmin):
    list_display = ["id", "endpoint", "mode", "method", "status_code", "response_ms", "success", "caller", "created_at"]
    list_filter = ["mode", "success"]
    search_fields = ["request_id", "endpoint__code", "caller"]
