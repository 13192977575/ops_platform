"""scripts 序列化器。"""
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Script, ScriptVersion

User = get_user_model()


class ScriptListSerializer(serializers.ModelSerializer):
    owner = serializers.CharField(source="owner.username", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    environment_name = serializers.CharField(
        source="environment.name", read_only=True, default=None
    )

    class Meta:
        model = Script
        fields = [
            "id",
            "name",
            "code",
            "description",
            "owner",
            "business",
            "business_name",
            "project",
            "project_name",
            "environment",
            "environment_name",
            "runner",
            "source_type",
            "status",
            "current_version",
            "timeout_seconds",
            "memory_limit_mb",
            "cpu_limit",
            "tags",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "owner", "current_version", "created_at", "updated_at"]


class ScriptDetailSerializer(ScriptListSerializer):
    """详情:附带当前版本代码、文件集与已配置的环境变量键。"""

    code = serializers.SerializerMethodField()
    env_vars = serializers.SerializerMethodField()

    class Meta(ScriptListSerializer.Meta):
        fields = ScriptListSerializer.Meta.fields + [
            "params_schema",
            "files",
            "env_vars",
            "code",
        ]

    def get_code(self, obj: Script) -> str:
        version = obj.current_version_obj
        return version.code if version else ""

    def get_env_vars(self, obj: Script) -> dict:
        # 只回显已配置的键名,敏感值一律 ***
        return {k: "***" for k in (obj.env_vars or {})}


class ScriptVersionSerializer(serializers.ModelSerializer):
    created_by = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = ScriptVersion
        fields = [
            "id",
            "script",
            "version",
            "changelog",
            "is_current",
            "created_by",
            "created_at",
            "code",
            "files",
        ]
        read_only_fields = ["id", "script", "version", "is_current", "created_by", "created_at"]


class CreateScriptSerializer(serializers.ModelSerializer):
    """创建脚本:code 为脚本编码,source_code 为初始代码(平台内维护,创建 v1 快照)。

    files 为附加文件集(可含 .env 等);env_vars 为环境变量(仅写入,敏感键加密存储)。
    """

    source_code = serializers.CharField(write_only=True, allow_blank=False)
    files = serializers.JSONField(required=False, default=list)
    env_vars = serializers.JSONField(write_only=True, required=False, default=dict)
    owner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Script
        fields = [
            "name",
            "code",
            "description",
            "owner",
            "business",
            "project",
            "environment",
            "runner",
            "params_schema",
            "timeout_seconds",
            "memory_limit_mb",
            "cpu_limit",
            "tags",
            "files",
            "env_vars",
            "source_code",
        ]


class CreateVersionSerializer(serializers.Serializer):
    code = serializers.CharField(allow_blank=False)
    changelog = serializers.CharField(required=False, allow_blank=True, default="")
    files = serializers.JSONField(required=False, default=None)  # None = 沿用 script.files


class ExecuteSerializer(serializers.Serializer):
    params = serializers.JSONField(required=False, default=dict)
