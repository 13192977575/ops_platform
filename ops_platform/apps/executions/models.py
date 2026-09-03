"""统一执行记录:三类资产(脚本/定时任务/接口)共用同一条执行链路。

asset 使用多态引用(asset_type + asset_id,不建 FK),避免跨 app 耦合;
business/project/environment 为创建时的冗余快照,支撑执行历史的数据范围过滤。
"""
from django.conf import settings
from django.db import models

from ops_platform.apps.accounts.models import Business, Environment, Project
from ops_platform.apps.common.models import BaseModel


class Execution(BaseModel):
    class AssetType(models.TextChoices):
        SCRIPT = "script", "脚本"
        SCHEDULE = "schedule", "定时任务"  # P3 启用
        ENDPOINT = "endpoint", "接口"  # P4 启用

    class TriggerType(models.TextChoices):
        MANUAL = "manual", "手工"
        SCHEDULE = "schedule", "定时"
        API = "api", "接口"

    class Status(models.TextChoices):
        PENDING = "pending", "等待执行"
        RUNNING = "running", "执行中"
        RETRYING = "retrying", "重试中"
        SUCCESS = "success", "成功"
        FAILED = "failed", "失败"
        TIMEOUT = "timeout", "超时"
        CANCELED = "canceled", "已取消"

    asset_type = models.CharField(
        "资产类型", max_length=16, choices=AssetType.choices, db_index=True
    )
    asset_id = models.PositiveBigIntegerField("资产 ID", db_index=True)
    trigger_type = models.CharField(
        "触发方式", max_length=16, choices=TriggerType.choices, default=TriggerType.MANUAL
    )
    trigger_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="触发人",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="triggered_executions",
    )
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    params = models.JSONField("执行参数", default=dict)
    result_code = models.IntegerField("退出码", null=True, blank=True)
    error_message = models.TextField("错误信息", blank=True)
    request_id = models.CharField("请求 ID", max_length=36, db_index=True)
    node = models.CharField("执行节点", max_length=64, blank=True)
    worker_id = models.CharField("Worker ID", max_length=64, blank=True)
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)
    duration_ms = models.IntegerField("耗时(毫秒)", null=True, blank=True)
    retry_count = models.PositiveIntegerField("重试次数", default=0)
    # 数据范围冗余快照(创建时从资产复制,用于执行历史过滤)
    business = models.ForeignKey(
        Business, verbose_name="业务线", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    project = models.ForeignKey(
        Project, verbose_name="项目", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    environment = models.ForeignKey(
        Environment, verbose_name="环境", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "执行记录"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["asset_type", "asset_id", "-created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.asset_type}:{self.asset_id} [{self.status}] #{self.pk}"

    @property
    def duration_text(self) -> str:
        if self.duration_ms is None:
            return "-"
        return f"{self.duration_ms / 1000:.2f}s"

    @property
    def asset_label(self) -> str | None:
        """资产显示名:按类型解析脚本/定时任务/接口的 name(code),供列表与详情展示。"""
        if self.asset_type == self.AssetType.SCRIPT:
            from ops_platform.apps.scripts.models import Script

            asset = Script.objects.filter(pk=self.asset_id).only("name", "code").first()
        elif self.asset_type == self.AssetType.SCHEDULE:
            from ops_platform.apps.schedules.models import ScheduleTask

            asset = ScheduleTask.objects.filter(pk=self.asset_id).only("name", "code").first()
        elif self.asset_type == self.AssetType.ENDPOINT:
            from ops_platform.apps.endpoints.models import HttpEndpoint

            asset = HttpEndpoint.objects.filter(pk=self.asset_id).only("name", "code").first()
        else:
            asset = None
        if asset is None:
            return None
        name = getattr(asset, "name", "") or str(asset)
        code = getattr(asset, "code", "") or ""
        return f"{name}({code})" if code else name
