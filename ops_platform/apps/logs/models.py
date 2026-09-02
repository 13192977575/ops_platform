"""统一日志条目:所有脚本/任务/接口执行日志统一入库,格式与字段固定。

安全要求:写入前必须经过 sensitive filter,密码/Token/连接串等敏感信息不允许落库。
"""
from django.db import models


class LogEntry(models.Model):
    """一条执行日志(JSON Lines 结构化入库)。"""

    execution = models.ForeignKey(
        "executions.Execution",
        verbose_name="执行记录",
        on_delete=models.CASCADE,
        related_name="logs",
    )
    request_id = models.CharField("请求 ID", max_length=36, blank=True, db_index=True)
    task_id = models.CharField("任务 ID", max_length=36, blank=True)
    user = models.CharField("执行人", max_length=64, blank=True)
    level = models.CharField("日志级别", max_length=16, default="INFO", db_index=True)
    node = models.CharField("执行节点", max_length=64, blank=True)
    message = models.TextField("日志内容")
    extra = models.JSONField("附加字段", default=dict)
    created_at = models.DateTimeField("时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "执行日志"
        verbose_name_plural = verbose_name
        permissions = [
            ("view_log", "可以查看日志"),
        ]
        indexes = [
            models.Index(fields=["execution", "id"]),
            models.Index(fields=["level", "created_at"]),
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"#{self.execution_id} [{self.level}] {self.message[:50]}"
