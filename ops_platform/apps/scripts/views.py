"""scripts 视图:资产 CRUD、启停、版本管理、手工执行入口。"""
from __future__ import annotations

import uuid

from django.db import transaction
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ops_platform.apps.accounts.permissions import DataScopeFilterBackend, HasPerm
from ops_platform.apps.accounts.scope import user_can_access
from ops_platform.apps.audit.mixins import AuditMixin
from ops_platform.apps.executions.models import Execution
from ops_platform.apps.executions.tasks import execute_asset

from .models import Script, ScriptVersion
from .params import validate_params, validate_schema
from .serializers import (
    CreateScriptSerializer,
    CreateVersionSerializer,
    ExecuteSerializer,
    ScriptDetailSerializer,
    ScriptListSerializer,
    ScriptVersionSerializer,
)

_PERM_MAP = {
    "list": "view_script",
    "retrieve": "view_script",
    "create": "create_script",
    "update": "update_script",
    "partial_update": "update_script",
    "destroy": "delete_script",
    "enable": "update_script",
    "disable": "update_script",
    "create_version": "update_script",
    "rollback": "update_script",
    "versions": "view_script",
    "execute": "execute_script",
}


class ScriptViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = (
        Script.objects.select_related("owner", "business", "project", "environment").all()
    )
    resource = "script"
    permission_classes = [IsAuthenticated, HasPerm]
    filter_backends = [
        DataScopeFilterBackend,
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["business", "project", "environment", "status", "runner", "source_type"]
    search_fields = ["name", "code", "description"]
    ordering_fields = ["created_at", "updated_at", "name", "code", "current_version"]
    ordering = ["id"]
    required_permission = _PERM_MAP

    def get_serializer_class(self):
        if self.action == "create":
            return CreateScriptSerializer
        if self.action == "retrieve":
            return ScriptDetailSerializer
        return ScriptListSerializer

    def create(self, request, *args, **kwargs):
        serializer = CreateScriptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        code = data.pop("source_code")
        files = data.pop("files", []) or []
        env_vars = data.pop("env_vars", {}) or {}
        schema = data.get("params_schema") or []
        schema_errors = validate_schema(schema)
        if schema_errors:
            return Response({"detail": schema_errors}, status=status.HTTP_400_BAD_REQUEST)
        if not data.get("owner"):
            data["owner"] = request.user
        with transaction.atomic():
            script = Script.objects.create(files=files, **data)
            script.set_env_vars(env_vars)  # 敏感键加密存储
            script.save(update_fields=["env_vars", "updated_at"])
            ScriptVersion.objects.create(
                script=script,
                version=1,
                code=code,
                files=files,
                env_vars=script.env_vars,  # 快照(已加密)
                params_schema=schema,
                created_by=request.user,
                is_current=True,
            )
            script.current_version = 1
            script.save(update_fields=["current_version", "updated_at"])
        self._audit(request, "create", script)
        return Response(
            ScriptDetailSerializer(script).data, status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        if "params_schema" in request.data:
            errors = validate_schema(request.data.get("params_schema") or [])
            if errors:
                return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        return super().update(request, *args, **kwargs)

    # ------------------------------------------------------------------ 启停
    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        script = self.get_object()
        script.status = Script.Status.ENABLED
        script.save(update_fields=["status", "updated_at"])
        self._audit(request, "enable", script)
        return Response({"id": script.pk, "status": script.status})

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        script = self.get_object()
        script.status = Script.Status.DISABLED
        script.save(update_fields=["status", "updated_at"])
        self._audit(request, "disable", script)
        return Response({"id": script.pk, "status": script.status})

    # ------------------------------------------------------------------ 版本
    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        script = self.get_object()
        qs = script.versions.all()
        page = self.paginate_queryset(qs)
        serializer = ScriptVersionSerializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def create_version(self, request, pk=None):
        script = self.get_object()
        serializer = CreateVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            old_current = script.versions.filter(is_current=True).first()
            new_version = script.current_version + 1
            files = serializer.validated_data.get("files")
            if files is None:
                files = script.files
            version = ScriptVersion.objects.create(
                script=script,
                version=new_version,
                code=serializer.validated_data["code"],
                files=files,
                env_vars=script.env_vars,  # 环境变量沿用脚本当前值(加密快照)
                params_schema=script.params_schema,
                changelog=serializer.validated_data.get("changelog", ""),
                created_by=request.user,
                is_current=True,
            )
            if old_current:
                old_current.is_current = False
                old_current.save(update_fields=["is_current", "updated_at"])
            script.current_version = new_version
            script.save(update_fields=["current_version", "updated_at"])
        self._audit(request, "version_create", script, extra={"version": new_version})
        return Response(ScriptVersionSerializer(version).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path=r"versions/(?P<version>[0-9]+)/rollback")
    def rollback(self, request, pk=None, version=None):
        script = self.get_object()
        target = get_object_or_404(ScriptVersion, script=script, version=int(version))
        with transaction.atomic():
            old_current = script.versions.filter(is_current=True).first()
            if old_current and old_current.pk != target.pk:
                old_current.is_current = False
                old_current.save(update_fields=["is_current", "updated_at"])
            target.is_current = True
            target.save(update_fields=["is_current", "updated_at"])
            script.current_version = target.version
            script.save(update_fields=["current_version", "updated_at"])
        self._audit(request, "version_rollback", script, extra={"version": target.version})
        return Response(ScriptVersionSerializer(target).data)

    # ------------------------------------------------------------------ 执行
    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        """手工执行:校验 → 创建 Execution(pending)→ 投递 Celery → 立即返回 execution_id。

        Web 请求不阻塞,耗时执行全部在 Worker 侧完成(需求约束)。
        """
        script = self.get_object()
        if not user_can_access(request.user, script):
            return Response(
                {"detail": "无权访问该脚本"}, status=status.HTTP_403_FORBIDDEN
            )
        if script.status != Script.Status.ENABLED:
            return Response(
                {"detail": "脚本未启用,不能执行"}, status=status.HTTP_400_BAD_REQUEST
            )
        s = ExecuteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        params, errors = validate_params(script.params_schema, s.validated_data.get("params") or {})
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        execution = Execution.objects.create(
            asset_type=Execution.AssetType.SCRIPT,
            asset_id=script.pk,
            trigger_type=Execution.TriggerType.MANUAL,
            trigger_user=request.user,
            params=params,
            request_id=str(uuid.uuid4()),
            business=script.business,
            project=script.project,
            environment=script.environment,
        )
        execute_asset.delay(execution.pk)
        self._audit(request, "execute", script, extra={"execution_id": execution.pk})
        return Response(
            {"execution_id": execution.pk, "status": execution.status},
            status=status.HTTP_202_ACCEPTED,
        )
