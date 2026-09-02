"""DRF 权限类:操作权限(RBAC)检查 + 数据范围自动过滤。

操作权限约定:
- 权限 codename 使用 <action>_<resource> 形式,如 execute_script、manage_schedule;
- 视图通过 required_permission 声明所需权限,如:
      class ScriptViewSet(viewsets.ModelViewSet):
          required_permission = "execute_script"
          permission_classes = [IsAuthenticated, HasPerm]
"""
from django.db.models import QuerySet
from rest_framework import permissions
from rest_framework.filters import BaseFilterBackend

from .scope import scope_queryset


class HasPerm(permissions.BasePermission):
    """按 view.required_permission 检查当前用户(自身或角色)是否持有该权限 codename。"""

    message = "没有执行该操作所需的权限"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        required = getattr(view, "required_permission", None)
        if callable(required):
            required = required(view)
        elif isinstance(required, dict):
            required = required.get(getattr(view, "action", None))
        if not required:
            return True
        return required in user.all_permission_codenames()


class DataScopeFilterBackend(BaseFilterBackend):
    """对含 business/project/environment 字段的资产 queryset 自动应用用户数据范围过滤。"""

    def filter_queryset(self, request, queryset: QuerySet, view):
        user = request.user
        if not user or not user.is_authenticated:
            return queryset.none()
        if user.is_superuser:
            return queryset
        model = queryset.model
        has_scope_fields = {
            f.name for f in model._meta.fields
        }.issuperset({"business", "project", "environment"})
        if not has_scope_fields:
            return queryset
        return scope_queryset(queryset, user)
