"""schedules 视图:定时任务 CRUD、启停、立即执行。"""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ops_platform.apps.accounts.permissions import DataScopeFilterBackend, HasPerm
from ops_platform.apps.audit.mixins import AuditMixin

from .models import ScheduleTask
from .serializers import (
    ScheduleTaskCreateSerializer,
    ScheduleTaskDetailSerializer,
    ScheduleTaskListSerializer,
)
from .tasks import run_schedule

_PERM_MAP = {
    "list": "view_schedule",
    "retrieve": "view_schedule",
    "create": "create_schedule",
    "update": "update_schedule",
    "partial_update": "update_schedule",
    "destroy": "delete_schedule",
    "enable": "update_schedule",
    "disable": "update_schedule",
    "run_now": "execute_schedule",
}


class ScheduleTaskViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = ScheduleTask.objects.select_related(
        "script", "business", "project", "environment", "owner", "periodic_task"
    ).all()
    resource = "schedule"
    permission_classes = [IsAuthenticated, HasPerm]
    filter_backends = [
        DataScopeFilterBackend,
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["business", "project", "environment", "enabled", "schedule_type", "script"]
    search_fields = ["name", "code", "description"]
    ordering_fields = [
        "created_at",
        "updated_at",
        "name",
        "code",
        "last_run_at",
        "consecutive_failures",
    ]
    ordering = ["id"]
    required_permission = _PERM_MAP

    def get_serializer_class(self):
        if self.action == "create":
            return ScheduleTaskCreateSerializer
        if self.action == "retrieve":
            return ScheduleTaskDetailSerializer
        return ScheduleTaskListSerializer

    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        schedule = self.get_object()
        schedule.enabled = True
        schedule.save(update_fields=["enabled", "updated_at"])  # 信号同步 PeriodicTask
        self._audit(request, "enable", schedule)
        return Response({"id": schedule.pk, "enabled": schedule.enabled})

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        schedule = self.get_object()
        schedule.enabled = False
        schedule.save(update_fields=["enabled", "updated_at"])
        self._audit(request, "disable", schedule)
        return Response({"id": schedule.pk, "enabled": schedule.enabled})

    @action(detail=True, methods=["post"])
    def run_now(self, request, pk=None):
        """立即触发一次调度(手动执行入口,异步投递,不阻塞请求)。"""
        schedule = self.get_object()
        if not schedule.enabled:
            return Response(
                {"detail": "任务未启用,无法立即执行"}, status=status.HTTP_400_BAD_REQUEST
            )
        run_schedule.delay(schedule.pk)
        self._audit(request, "run_now", schedule)
        return Response({"id": schedule.pk, "dispatched": True}, status=status.HTTP_202_ACCEPTED)
