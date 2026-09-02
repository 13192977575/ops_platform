"""日志检索过滤集:时间范围、任务/用户/级别/请求 ID。"""
import django_filters

from .models import LogEntry


class LogEntryFilter(django_filters.FilterSet):
    created_after = django_filters.IsoDateTimeFilter(
        field_name="created_at", lookup_expr="gte", label="开始时间"
    )
    created_before = django_filters.IsoDateTimeFilter(
        field_name="created_at", lookup_expr="lte", label="结束时间"
    )

    class Meta:
        model = LogEntry
        fields = [
            "execution",
            "level",
            "user",
            "request_id",
            "created_after",
            "created_before",
        ]
