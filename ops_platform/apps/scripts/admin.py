"""scripts 后台管理。"""
from django.contrib import admin

from .models import Script, ScriptVersion


class ScriptVersionInline(admin.TabularInline):
    model = ScriptVersion
    extra = 0
    readonly_fields = ["version", "created_by", "is_current", "created_at"]
    fields = ["version", "changelog", "is_current", "created_by", "created_at"]


@admin.register(Script)
class ScriptAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "code",
        "business",
        "project",
        "environment",
        "owner",
        "status",
        "current_version",
        "timeout_seconds",
    ]
    list_filter = ["status", "business", "environment", "runner"]
    search_fields = ["name", "code"]
    autocomplete_fields = ["business", "project", "owner"]
    inlines = [ScriptVersionInline]


@admin.register(ScriptVersion)
class ScriptVersionAdmin(admin.ModelAdmin):
    list_display = ["script", "version", "is_current", "created_by", "created_at"]
    list_filter = ["is_current"]
    search_fields = ["script__code", "script__name"]
