"""executions 后台管理:执行记录 + 日志聚合预览。"""
from django.contrib import admin
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ops_platform.apps.logs.models import LogEntry

from .models import Execution

# 详情页日志预览最大行数(超长日志提示用 API/日志中心查全文)
MAX_LOG_PREVIEW = 500


class LogEntryInline(admin.TabularInline):
    model = LogEntry
    extra = 0
    readonly_fields = ["created_at"]
    can_delete = False


@admin.register(Execution)
class ExecutionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "asset_type",
        "asset_label",
        "trigger_type",
        "trigger_user",
        "status",
        "request_id",
        "node",
        "duration_ms",
        "created_at",
    ]
    list_filter = ["asset_type", "trigger_type", "status", "business", "environment"]
    search_fields = ["request_id", "error_message"]
    # 日志量大时内联逐行渲染会拖垮页面,改为只读聚合预览(见 log_preview)
    # inlines = [LogEntryInline]
    readonly_fields = [
        "asset_label",
        "log_preview",
    ]

    @admin.display(description="资产")
    def asset_label(self, obj):
        return obj.asset_label or f"#{obj.asset_id}(已删除)"

    @admin.display(description="执行日志(预览)")
    def log_preview(self, obj):
        total = obj.logs.count()
        lines = list(
            obj.logs.order_by("id").values_list("message", flat=True)[:MAX_LOG_PREVIEW]
        )
        if not lines:
            return mark_safe("<span style='color:#999'>暂无日志</span>")
        if total > len(lines):
            lines.append(
                f"... (仅预览前 {len(lines)} 行,共 {total} 行;"
                f"完整日志请用 GET /api/executions/{obj.pk}/logs/ 或「日志中心」按执行记录查询)"
            )
        text = "\n".join(lines)
        html = (
            '<pre style="max-height:480px;overflow:auto;white-space:pre-wrap;'
            'word-break:break-all;background:#1e1e1e;color:#d4d4d4;padding:10px;'
            'border-radius:4px;font-size:12px">{}</pre>'
        )
        return mark_safe(html.format(escape(text)))


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ["id", "execution", "level", "user", "node", "message", "created_at"]
    list_filter = ["level"]
    search_fields = ["message", "request_id"]
