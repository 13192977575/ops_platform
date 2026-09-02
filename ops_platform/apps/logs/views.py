"""日志中心视图:统一检索(时间/任务/用户/级别/关键字),只读。"""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated

from ops_platform.apps.accounts.permissions import HasPerm
from ops_platform.apps.accounts.scope import build_scope_q, get_user_scopes

from .filters import LogEntryFilter
from .models import LogEntry
from .serializers import LogEntrySerializer

_PERM_MAP = {
    "list": "view_log",
    "retrieve": "view_log",
}


class LogEntryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LogEntry.objects.select_related("execution").all()
    serializer_class = LogEntrySerializer
    permission_classes = [IsAuthenticated, HasPerm]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = LogEntryFilter
    search_fields = ["message", "request_id", "user"]
    ordering_fields = ["created_at", "level"]
    ordering = ["-created_at"]
    required_permission = _PERM_MAP

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        # 数据范围:仅可见其授权业务/项目/环境内执行记录产生的日志
        q = build_scope_q(
            get_user_scopes(user),
            "execution__business",
            "execution__project",
            "execution__environment",
        )
        return qs.filter(q) if q is not None else qs.none()
