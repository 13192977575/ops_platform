"""endpoints 视图:接口 CRUD、启停、暴露调用入口(expose)。"""
from __future__ import annotations

import uuid

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from ops_platform.apps.accounts.permissions import DataScopeFilterBackend, HasPerm
from ops_platform.apps.audit.mixins import AuditMixin
from ops_platform.apps.audit.services import (
    ACTION_ENDPOINT_INVOKE,
    request_ip,
    write_audit,
)
from ops_platform.apps.executions.models import Execution
from ops_platform.apps.executions.tasks import execute_asset
from ops_platform.apps.scripts.params import validate_params

from .models import EndpointCallLog, HttpEndpoint
from .serializers import EndpointSerializer

_PERM_MAP = {
    "list": "view_endpoint",
    "retrieve": "view_endpoint",
    "create": "create_endpoint",
    "update": "update_endpoint",
    "partial_update": "update_endpoint",
    "destroy": "delete_endpoint",
    "enable": "update_endpoint",
    "disable": "update_endpoint",
}


class EndpointViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = HttpEndpoint.objects.select_related(
        "script", "business", "project", "environment"
    ).all()
    serializer_class = EndpointSerializer
    resource = "endpoint"
    permission_classes = [IsAuthenticated, HasPerm]
    filter_backends = [
        DataScopeFilterBackend,
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["business", "project", "environment", "mode", "status", "auth_type"]
    search_fields = ["name", "code", "description", "url"]
    ordering_fields = [
        "created_at",
        "updated_at",
        "name",
        "code",
        "call_count",
        "error_rate",
    ]
    ordering = ["id"]
    required_permission = _PERM_MAP

    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        endpoint = self.get_object()
        endpoint.status = "enabled"
        endpoint.save(update_fields=["status", "updated_at"])
        self._audit(request, "enable", endpoint)
        return Response({"id": endpoint.pk, "status": endpoint.status})

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        endpoint = self.get_object()
        endpoint.status = "disabled"
        endpoint.save(update_fields=["status", "updated_at"])
        self._audit(request, "disable", endpoint)
        return Response({"id": endpoint.pk, "status": endpoint.status})


class EndpointInvokeView(APIView):
    """POST /api/endpoints/invoke/{code}/ 调用暴露接口(第三方入口)。

    认证:
    - auth_type=api_key:校验 X-API-Key 请求头(仅存哈希);
    - auth_type=none:要求 JWT 认证 + execute_endpoint 权限。
    执行全程异步:创建 Execution(pending)→ 投递 → 返回 execution_id,调用方轮询 executions API。
    """

    authentication_classes = []  # 手动认证(API Key 场景无 JWT)
    permission_classes = []

    def post(self, request, code: str):
        endpoint = HttpEndpoint.objects.filter(code=code).first()
        if endpoint is None:
            return Response({"detail": "接口不存在"}, status=status.HTTP_404_NOT_FOUND)
        if endpoint.mode != HttpEndpoint.Mode.EXPOSE:
            return Response(
                {"detail": "该接口不是暴露模式"}, status=status.HTTP_400_BAD_REQUEST
            )
        if endpoint.status != "enabled":
            return Response({"detail": "接口未启用"}, status=status.HTTP_400_BAD_REQUEST)

        caller = ""
        if endpoint.auth_type == HttpEndpoint.AuthType.API_KEY:
            key = request.headers.get("X-API-Key", "")
            if not endpoint.verify_api_key(key):
                return Response({"detail": "API Key 无效"}, status=status.HTTP_401_UNAUTHORIZED)
            caller = f"api_key:{endpoint.code}"
        else:
            auth = JWTAuthentication().authenticate(request)
            if auth is not None:
                request.user, _ = auth
            if not getattr(request.user, "is_authenticated", False):
                return Response({"detail": "未认证"}, status=status.HTTP_401_UNAUTHORIZED)
            if not (
                request.user.is_superuser
                or "execute_endpoint" in request.user.all_permission_codenames()
            ):
                return Response({"detail": "没有调用权限"}, status=status.HTTP_403_FORBIDDEN)
            caller = request.user.username

        params, errors = validate_params(
            endpoint.params_schema, request.data.get("params", request.data)
        )
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)

        execution = Execution.objects.create(
            asset_type=Execution.AssetType.ENDPOINT,
            asset_id=endpoint.pk,
            trigger_type=Execution.TriggerType.API,
            trigger_user=(
                request.user
                if getattr(request.user, "is_authenticated", False)
                else None
            ),
            params=params,
            request_id=str(uuid.uuid4()),
            business=endpoint.business,
            project=endpoint.project,
            environment=endpoint.environment,
        )
        EndpointCallLog.objects.create(
            endpoint=endpoint,
            mode=HttpEndpoint.Mode.EXPOSE,
            method="POST",
            url=f"/api/endpoints/invoke/{code}/",
            request_id=execution.request_id,
            caller=caller,
        )
        execute_asset.delay(execution.pk)
        write_audit(
            request.user,
            ACTION_ENDPOINT_INVOKE,
            target_type="endpoint",
            target_id=endpoint.pk,
            detail={"caller": caller, "execution_id": execution.pk},
            ip=request_ip(request),
        )
        return Response(
            {"execution_id": execution.pk, "status": execution.status},
            status=status.HTTP_202_ACCEPTED,
        )
