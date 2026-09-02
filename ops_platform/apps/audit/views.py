"""audit 视图:审计日志查询(只读)。"""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated

from ops_platform.apps.accounts.permissions import HasPerm

from .models import AuditLog
from .serializers import AuditLogSerializer

_PERM_MAP = {
    "list": "view_auditlog",
    "retrieve": "view_auditlog",
}


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("actor").all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, HasPerm]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["action", "target_type", "actor"]
    search_fields = ["action", "target_type", "target_id"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    required_permission = _PERM_MAP
