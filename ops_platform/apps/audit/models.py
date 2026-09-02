"""审计日志模型:关键操作审计,仅追加、不可修改/删除。"""
from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """一条审计记录(登录、资产增删改启停、执行等关键操作)。"""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="操作人",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    action = models.CharField("动作", max_length=64, db_index=True)
    target_type = models.CharField("对象类型", max_length=32, blank=True, db_index=True)
    target_id = models.CharField("对象 ID", max_length=32, blank=True)
    detail = models.JSONField("详情", default=dict)
    ip = models.CharField("来源 IP", max_length=64, blank=True)
    created_at = models.DateTimeField("时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "审计日志"
        verbose_name_plural = verbose_name
        # view_auditlog 由模型默认权限提供(命名恰好匹配约定)
        ordering = ["-created_at"]

    def __str__(self) -> str:
        actor = getattr(self.actor, "username", "-")
        return f"[{self.created_at:%Y-%m-%d %H:%M:%S}] {actor} {self.action}"

    # ---------------- 仅追加保护 ----------------
    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise NotImplementedError("审计日志仅追加,不允许修改")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NotImplementedError("审计日志仅追加,不允许删除")
