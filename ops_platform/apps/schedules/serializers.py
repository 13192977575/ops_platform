"""schedules 序列化器。"""
from django.contrib.auth import get_user_model
from rest_framework import serializers

from ops_platform.apps.executions.models import Execution

from .cron import parse_cron
from .models import ScheduleTask

User = get_user_model()


class ScheduleTaskListSerializer(serializers.ModelSerializer):
    script_name = serializers.CharField(source="script.name", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    environment_name = serializers.CharField(
        source="environment.name", read_only=True, default=None
    )
    next_run_at = serializers.SerializerMethodField()
    recent_status = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleTask
        fields = [
            "id",
            "name",
            "code",
            "description",
            "script",
            "script_name",
            "schedule_type",
            "cron_expr",
            "interval_seconds",
            "timezone",
            "enabled",
            "timeout",
            "max_retries",
            "retry_delay",
            "concurrency_limit",
            "business",
            "business_name",
            "project",
            "project_name",
            "environment",
            "environment_name",
            "last_run_at",
            "next_run_at",
            "consecutive_failures",
            "recent_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "next_run_at",
            "last_run_at",
            "consecutive_failures",
            "recent_status",
            "created_at",
            "updated_at",
        ]

    def get_next_run_at(self, obj: ScheduleTask):
        return obj.next_run_at

    def get_recent_status(self, obj: ScheduleTask):
        execution = (
            Execution.objects.filter(
                asset_type=Execution.AssetType.SCHEDULE, asset_id=obj.pk
            )
            .only("status")
            .first()
        )
        return execution.status if execution else None


class ScheduleTaskDetailSerializer(ScheduleTaskListSerializer):
    class Meta(ScheduleTaskListSerializer.Meta):
        fields = ScheduleTaskListSerializer.Meta.fields + ["params"]


class ScheduleTaskCreateSerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = ScheduleTask
        fields = [
            "id",
            "name",
            "code",
            "description",
            "script",
            "schedule_type",
            "cron_expr",
            "interval_seconds",
            "timezone",
            "enabled",
            "timeout",
            "max_retries",
            "retry_delay",
            "concurrency_limit",
            "params",
            "owner",
            "business",
            "project",
            "environment",
        ]

    def create(self, validated_data):
        if not validated_data.get("owner"):
            request = self.context.get("request")
            if request is not None:
                validated_data["owner"] = request.user
        return super().create(validated_data)

    def validate(self, attrs):
        schedule_type = attrs.get("schedule_type")
        if schedule_type == ScheduleTask.ScheduleType.CRON:
            expr = attrs.get("cron_expr")
            if not expr:
                raise serializers.ValidationError({"cron_expr": "cron 方式必须填写 cron_expr"})
            try:
                parse_cron(expr)
            except ValueError as exc:
                raise serializers.ValidationError({"cron_expr": str(exc)})
        elif schedule_type == ScheduleTask.ScheduleType.INTERVAL:
            if not attrs.get("interval_seconds"):
                raise serializers.ValidationError(
                    {"interval_seconds": "interval 方式必须填写 interval_seconds"}
                )
        return attrs
