"""endpoints 序列化器。"""
from rest_framework import serializers

from .models import HttpEndpoint


class EndpointSerializer(serializers.ModelSerializer):
    script_name = serializers.CharField(source="script.name", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    environment_name = serializers.CharField(
        source="environment.name", read_only=True, default=None
    )
    # 仅写入:创建/更新时传入明文,永不回显
    auth_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True, help_text="仅写入,创建后不回显"
    )

    class Meta:
        model = HttpEndpoint
        fields = [
            "id",
            "name",
            "code",
            "description",
            "mode",
            "script",
            "script_name",
            "method",
            "url",
            "auth_type",
            "auth_key",
            "status",
            "timeout",
            "version",
            "params_schema",
            "business",
            "business_name",
            "project",
            "project_name",
            "environment",
            "environment_name",
            "health_status",
            "avg_response_ms",
            "error_rate",
            "call_count",
            "last_check_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "health_status",
            "avg_response_ms",
            "error_rate",
            "call_count",
            "last_check_at",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        mode = attrs.get("mode")
        if mode == HttpEndpoint.Mode.EXPOSE:
            if not attrs.get("script"):
                raise serializers.ValidationError({"script": "expose 模式必须绑定脚本"})
            if (
                attrs.get("auth_type") == HttpEndpoint.AuthType.API_KEY
                and not attrs.get("auth_key")
            ):
                raise serializers.ValidationError(
                    {"auth_key": "API Key 认证必须提供 auth_key"}
                )
        elif mode == HttpEndpoint.Mode.MONITOR:
            if not attrs.get("url"):
                raise serializers.ValidationError(
                    {"url": "monitor 模式必须填写外部 URL"}
                )
        return attrs

    def create(self, validated_data):
        auth_key = validated_data.pop("auth_key", "") or ""
        endpoint = super().create(validated_data)
        if auth_key:
            endpoint.set_api_key(auth_key)
            endpoint.save(update_fields=["auth_key_hash"])
        return endpoint

    def update(self, instance, validated_data):
        auth_key = validated_data.pop("auth_key", None)
        endpoint = super().update(instance, validated_data)
        if auth_key:
            endpoint.set_api_key(auth_key)
            endpoint.save(update_fields=["auth_key_hash"])
        return endpoint
