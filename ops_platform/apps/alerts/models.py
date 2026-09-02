"""告警模型:渠道(加密凭据)、规则(指标驱动)、记录(发送/静默/确认)。"""
from django.conf import settings
from django.db import models

from ops_platform.apps.accounts.models import Business
from ops_platform.apps.common.models import BaseModel

from .crypto import decrypt_config, encrypt_config


class AlertChannel(BaseModel):
    """告警渠道:企业微信/钉钉机器人、邮件、通用 Webhook。凭据敏感键加密存储。"""

    class ChannelType(models.TextChoices):
        WECOM = "wecom", "企业微信机器人"
        DINGTALK = "dingtalk", "钉钉机器人"
        EMAIL = "email", "邮件"
        WEBHOOK = "webhook", "Webhook"

    name = models.CharField("渠道名称", max_length=64, unique=True)
    type = models.CharField("渠道类型", max_length=16, choices=ChannelType.choices)
    config = models.JSONField(
        "配置",
        default=dict,
        help_text="敏感键(webhook_url/secret/token 等)加密存储,读取时不回显明文",
    )
    enabled = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "告警渠道"
        verbose_name_plural = verbose_name
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.name}({self.type})"

    def set_config(self, plain_config: dict) -> None:
        """加密敏感键后写入配置。"""
        self.config = encrypt_config(plain_config)

    def get_config(self) -> dict:
        """返回解密后的明文配置(供发送服务使用)。"""
        return decrypt_config(self.config)


class AlertRule(BaseModel):
    """告警规则:监控对象(资产)+ 指标 + 阈值 + 渠道 + 静默收敛。"""

    class AssetType(models.TextChoices):
        SCRIPT = "script", "脚本"
        SCHEDULE = "schedule", "定时任务"
        ENDPOINT = "endpoint", "接口"

    class Metric(models.TextChoices):
        CONSECUTIVE_FAILURES = "consecutive_failures", "连续失败次数"
        TIMEOUT = "timeout", "执行超时"
        ENDPOINT_UNAVAILABLE = "endpoint_unavailable", "接口不可用"
        ENDPOINT_SLOW = "endpoint_slow", "接口响应时间超限"

    class Severity(models.TextChoices):
        INFO = "info", "提示"
        WARNING = "warning", "警告"
        CRITICAL = "critical", "严重"

    name = models.CharField("规则名称", max_length=64)
    description = models.TextField("描述", blank=True)
    asset_type = models.CharField("监控对象类型", max_length=16, choices=AssetType.choices)
    asset_id = models.PositiveBigIntegerField("监控对象 ID")
    metric = models.CharField("指标", max_length=32, choices=Metric.choices)
    threshold = models.FloatField(
        "阈值", default=1,
        help_text="连续失败次数 / 接口响应时间毫秒(不可用/超时规则忽略)",
    )
    severity = models.CharField(
        "级别", max_length=16, choices=Severity.choices, default=Severity.WARNING
    )
    channels = models.ManyToManyField(
        AlertChannel, verbose_name="告警渠道", blank=True, related_name="rules"
    )
    silent_minutes = models.PositiveIntegerField(
        "静默窗口(分钟)", default=30, help_text="同一规则在该窗口内不重复发送"
    )
    enabled = models.BooleanField("启用", default=True)
    business = models.ForeignKey(
        Business, verbose_name="业务线", on_delete=models.PROTECT, related_name="alert_rules"
    )

    class Meta:
        verbose_name = "告警规则"
        verbose_name_plural = verbose_name
        permissions = [
            ("view_alert", "可以查看告警"),
            ("create_alert", "可以创建告警"),
            ("update_alert", "可以修改告警"),
            ("delete_alert", "可以删除告警"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["asset_type", "asset_id", "metric", "business"],
                name="uniq_alert_rule_asset_metric",
            )
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.name}({self.asset_type}:{self.asset_id} {self.metric})"


class AlertRecord(BaseModel):
    """告警记录:每次触发生成,含发送结果与确认信息。"""

    class Status(models.TextChoices):
        SENT = "sent", "已发送"
        SILENCED = "silenced", "静默抑制"
        FAILED = "failed", "发送失败"
        ACKED = "acked", "已确认"

    rule = models.ForeignKey(
        AlertRule,
        verbose_name="规则",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="records",
    )
    asset_type = models.CharField("对象类型", max_length=16)
    asset_id = models.PositiveBigIntegerField("对象 ID")
    metric = models.CharField("指标", max_length=32)
    severity = models.CharField("级别", max_length=16)
    message = models.TextField("告警内容")
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.SENT, db_index=True
    )
    channels = models.JSONField("发送渠道", default=list)
    send_result = models.JSONField("发送结果", default=dict)
    acked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="确认人",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    acked_at = models.DateTimeField("确认时间", null=True, blank=True)

    class Meta:
        verbose_name = "告警记录"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["rule", "-created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.asset_type}:{self.asset_id} {self.metric} ({self.status})"
