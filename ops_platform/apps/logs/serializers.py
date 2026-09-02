"""logs 序列化器。"""
from rest_framework import serializers

from .models import LogEntry


class LogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LogEntry
        fields = [
            "id",
            "execution",
            "request_id",
            "user",
            "level",
            "node",
            "message",
            "extra",
            "created_at",
        ]
        read_only_fields = fields
