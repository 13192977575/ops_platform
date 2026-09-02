"""审计埋点 mixin:ViewSet 声明 resource 后自动记录增删改与启停动作。"""
from __future__ import annotations

from .services import request_ip, write_audit


class AuditMixin:
    """为 ViewSet 提供统一审计埋点。

    用法:
        class ScriptViewSet(AuditMixin, viewsets.ModelViewSet):
            resource = "script"
    """

    resource: str = "asset"

    def _audit(self, request, action: str, obj=None, extra: dict | None = None) -> None:
        detail = dict(extra or {})
        if obj is not None:
            detail.setdefault("code", getattr(obj, "code", str(getattr(obj, "pk", ""))))
        write_audit(
            request.user,
            f"{self.resource}.{action}",
            target_type=self.resource,
            target_id=getattr(obj, "pk", None),
            detail=detail,
            ip=request_ip(request),
        )

    def perform_create(self, serializer):
        instance = serializer.save()
        self._audit(self.request, "create", instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        self._audit(self.request, "update", instance)

    def perform_destroy(self, instance):
        self._audit(self.request, "delete", instance)
        instance.delete()
