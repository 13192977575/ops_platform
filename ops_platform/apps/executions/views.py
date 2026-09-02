"""executions 视图:执行历史(只读)、详情、日志分页。"""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ops_platform.apps.accounts.permissions import DataScopeFilterBackend, HasPerm

from .models import Execution
from .serializers import (
    ExecutionDetailSerializer,
    ExecutionListSerializer,
    LogEntrySerializer,
)

_PERM_MAP = {
    "list": "view_execution",
    "retrieve": "view_execution",
    "logs": "view_execution",
}


class ExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Execution.objects.select_related(
        "trigger_user", "business", "project", "environment"
    ).all()
    permission_classes = [IsAuthenticated, HasPerm]
    filter_backends = [
        DataScopeFilterBackend,
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "asset_type",
        "asset_id",
        "status",
        "trigger_type",
        "business",
        "project",
        "environment",
    ]
    search_fields = ["request_id"]
    ordering_fields = ["created_at", "started_at", "duration_ms"]
    ordering = ["-created_at"]
    required_permission = _PERM_MAP

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ExecutionDetailSerializer
        return ExecutionListSerializer

    @action(detail=True, methods=["get"])
    def logs(self, request, pk=None):
        """GET /api/executions/{id}/logs/ 执行日志(分页,按时间正序)。"""
        execution = self.get_object()
        qs = execution.logs.all()
        page = self.paginate_queryset(qs)
        serializer = LogEntrySerializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
