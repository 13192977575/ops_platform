"""alerts 视图:渠道/规则 CRUD、规则启停、告警记录查看与确认。"""
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ops_platform.apps.accounts.permissions import DataScopeFilterBackend, HasPerm

from .models import AlertChannel, AlertRecord, AlertRule
from .serializers import AlertChannelSerializer, AlertRecordSerializer, AlertRuleSerializer

_ALERT_PERM = {
    "list": "view_alert",
    "retrieve": "view_alert",
    "create": "create_alert",
    "update": "update_alert",
    "partial_update": "update_alert",
    "destroy": "delete_alert",
}


class AlertChannelViewSet(viewsets.ModelViewSet):
    """告警渠道(全局,无数据范围)。"""

    queryset = AlertChannel.objects.all()
    serializer_class = AlertChannelSerializer
    permission_classes = [IsAuthenticated, HasPerm]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering = ["id"]
    required_permission = _ALERT_PERM


class AlertRuleViewSet(viewsets.ModelViewSet):
    """告警规则(按数据范围过滤)。"""

    queryset = AlertRule.objects.select_related("business").prefetch_related("channels").all()
    serializer_class = AlertRuleSerializer
    permission_classes = [IsAuthenticated, HasPerm]
    filter_backends = [
        DataScopeFilterBackend,
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["business", "asset_type", "asset_id", "metric", "severity", "enabled"]
    search_fields = ["name", "description"]
    ordering = ["id"]
    required_permission = {**_ALERT_PERM, "enable": "update_alert", "disable": "update_alert"}

    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        rule = self.get_object()
        rule.enabled = True
        rule.save(update_fields=["enabled", "updated_at"])
        return Response({"id": rule.pk, "enabled": rule.enabled})

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        rule = self.get_object()
        rule.enabled = False
        rule.save(update_fields=["enabled", "updated_at"])
        return Response({"id": rule.pk, "enabled": rule.enabled})


class AlertRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """告警记录:只读 + 确认(ack)。"""

    queryset = AlertRecord.objects.select_related("rule", "acked_by").all()
    serializer_class = AlertRecordSerializer
    permission_classes = [IsAuthenticated, HasPerm]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["status", "metric", "severity", "asset_type", "asset_id", "rule"]
    search_fields = ["message"]
    ordering = ["-created_at"]
    required_permission = {
        "list": "view_alert",
        "retrieve": "view_alert",
        "ack": "update_alert",
    }

    @action(detail=True, methods=["post"])
    def ack(self, request, pk=None):
        """确认告警:标记已确认(acknowledged)。"""
        record = self.get_object()
        record.status = AlertRecord.Status.ACKED
        record.acked_by = request.user
        record.acked_at = timezone.now()
        record.save(update_fields=["status", "acked_by", "acked_at", "updated_at"])
        return Response(AlertRecordSerializer(record).data)
