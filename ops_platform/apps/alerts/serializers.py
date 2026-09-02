"""alerts 序列化器。"""
from rest_framework import serializers

from .models import AlertChannel, AlertRecord, AlertRule


class AlertChannelSerializer(serializers.ModelSerializer):
    """渠道:config 接收明文(敏感键加密落库),读取时加密键脱敏为 ***。"""

    class Meta:
        model = AlertChannel
        fields = ["id", "name", "type", "config", "enabled", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        config = validated_data.pop("config", {}) or {}
        channel = super().create(validated_data)
        channel.set_config(config)
        channel.save(update_fields=["config"])
        return channel

    def update(self, instance, validated_data):
        config = validated_data.pop("config", None)
        channel = super().update(instance, validated_data)
        if config is not None:
            channel.set_config(config)
            channel.save(update_fields=["config"])
        return channel

    def to_representation(self, instance):
        data = super().to_representation(instance)
        config = instance.config or {}
        data["config"] = {
            k: ("***" if isinstance(v, str) and v.startswith("enc:") else v)
            for k, v in config.items()
        }
        return data


class AlertRuleSerializer(serializers.ModelSerializer):
    channels = serializers.PrimaryKeyRelatedField(
        many=True, queryset=AlertChannel.objects.all(), required=False
    )
    asset_name = serializers.SerializerMethodField()
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = AlertRule
        fields = [
            "id",
            "name",
            "description",
            "asset_type",
            "asset_id",
            "asset_name",
            "metric",
            "threshold",
            "severity",
            "channels",
            "silent_minutes",
            "enabled",
            "business",
            "business_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "asset_name", "business_name", "created_at", "updated_at"]

    def get_asset_name(self, obj: AlertRule):
        if obj.asset_type == AlertRule.AssetType.SCRIPT:
            from ops_platform.apps.scripts.models import Script

            asset = Script.objects.filter(pk=obj.asset_id).only("name", "code").first()
        elif obj.asset_type == AlertRule.AssetType.SCHEDULE:
            from ops_platform.apps.schedules.models import ScheduleTask

            asset = ScheduleTask.objects.filter(pk=obj.asset_id).only("name", "code").first()
        elif obj.asset_type == AlertRule.AssetType.ENDPOINT:
            from ops_platform.apps.endpoints.models import HttpEndpoint

            asset = HttpEndpoint.objects.filter(pk=obj.asset_id).only("name", "code").first()
        else:
            asset = None
        return f"{asset.name}({asset.code})" if asset else None

    def validate(self, attrs):
        asset_type = attrs.get("asset_type")
        asset_id = attrs.get("asset_id")
        if asset_type and asset_id is not None and not self._asset_exists(asset_type, asset_id):
            raise serializers.ValidationError(
                {"asset_id": f"{asset_type} 资产不存在(id={asset_id})"}
            )
        return attrs

    @staticmethod
    def _asset_exists(asset_type: str, asset_id: int) -> bool:
        if asset_type == AlertRule.AssetType.SCRIPT:
            from ops_platform.apps.scripts.models import Script

            return Script.objects.filter(pk=asset_id).exists()
        if asset_type == AlertRule.AssetType.SCHEDULE:
            from ops_platform.apps.schedules.models import ScheduleTask

            return ScheduleTask.objects.filter(pk=asset_id).exists()
        if asset_type == AlertRule.AssetType.ENDPOINT:
            from ops_platform.apps.endpoints.models import HttpEndpoint

            return HttpEndpoint.objects.filter(pk=asset_id).exists()
        return False


class AlertRecordSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source="rule.name", read_only=True)
    acked_by = serializers.CharField(source="acked_by.username", read_only=True)

    class Meta:
        model = AlertRecord
        fields = [
            "id",
            "rule",
            "rule_name",
            "asset_type",
            "asset_id",
            "metric",
            "severity",
            "message",
            "status",
            "channels",
            "send_result",
            "acked_by",
            "acked_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
