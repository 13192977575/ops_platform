"""executions 序列化器。"""
from rest_framework import serializers

from ops_platform.apps.logs.models import LogEntry

from .models import Execution


class ExecutionListSerializer(serializers.ModelSerializer):
    trigger_user = serializers.CharField(source="trigger_user.username", read_only=True)
    asset_name = serializers.SerializerMethodField()
    business_name = serializers.CharField(source="business.name", read_only=True, default=None)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    environment_name = serializers.CharField(
        source="environment.name", read_only=True, default=None
    )

    class Meta:
        model = Execution
        fields = [
            "id",
            "asset_type",
            "asset_id",
            "asset_name",
            "trigger_type",
            "trigger_user",
            "status",
            "request_id",
            "node",
            "started_at",
            "finished_at",
            "duration_ms",
            "retry_count",
            "error_message",
            "business",
            "business_name",
            "project",
            "project_name",
            "environment",
            "environment_name",
            "created_at",
        ]
        read_only_fields = fields

    def get_asset_name(self, obj: Execution):
        if obj.asset_type == Execution.AssetType.SCRIPT:
            from ops_platform.apps.scripts.models import Script

            script = (
                Script.objects.filter(pk=obj.asset_id).only("name", "code").first()
            )
            return f"{script.name}({script.code})" if script else None
        return None


class ExecutionDetailSerializer(ExecutionListSerializer):
    class Meta(ExecutionListSerializer.Meta):
        fields = ExecutionListSerializer.Meta.fields + ["params", "result_code", "worker_id"]


class LogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LogEntry
        fields = [
            "id",
            "request_id",
            "user",
            "level",
            "node",
            "message",
            "extra",
            "created_at",
        ]
        read_only_fields = fields
