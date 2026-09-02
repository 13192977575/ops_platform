"""accounts 后台管理(开发/运营便利)。"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group

from .models import Business, DataScope, Environment, Project, Role, User

admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ["username", "display_name", "source", "is_active", "is_staff"]
    list_filter = ["source", "is_active", "is_staff"]
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("平台扩展", {"fields": ("display_name", "source", "phone", "roles")}),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "enabled"]
    list_filter = ["enabled"]
    filter_horizontal = ["permissions"]


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "enabled"]
    search_fields = ["name", "code"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "business", "enabled"]
    list_filter = ["business"]
    search_fields = ["name", "code"]


@admin.register(Environment)
class EnvironmentAdmin(admin.ModelAdmin):
    list_display = ["name", "code"]


@admin.register(DataScope)
class DataScopeAdmin(admin.ModelAdmin):
    list_display = ["role", "user", "business", "project", "environment"]
    list_filter = ["business", "environment"]
    autocomplete_fields = ["business", "project"]
