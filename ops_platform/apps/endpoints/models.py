"""HTTP 接口资产模型。

两种模式(D4 一期):
- expose:把平台内脚本暴露为 HTTP API(第三方/平台内调用),支持 API Key 认证;
- monitor:登记外部接口 URL,由巡检任务周期探测,维护健康统计。
安全:API Key 仅存哈希,绝不明文落库;auth_key 字段只写不回显。
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from ops_platform.apps.accounts.models import Business, Environment, Project
from ops_platform.apps.common.models import BaseModel
from ops_platform.apps.scripts.models import Script


class HttpEndpoint(BaseModel):
    class Mode(models.TextChoices):
        EXPOSE = "expose", "暴露平台能力"
        MONITOR = "monitor", "监控外部接口"

    class AuthType(models.TextChoices):
        NONE = "none", "无需认证"
        API_KEY = "api_key", "API Key"

    class HealthStatus(models.TextChoices):
        UNKNOWN = "unknown", "未知"
        HEALTHY = "healthy", "健康"
        DEGRADED = "degraded", "异常"
        DOWN = "down", "不可用"

    name = models.CharField("接口名称", max_length=64)
    code = models.CharField("接口编码", max_length=32, help_text="业务线内唯一,expose 调用路径标识")
    description = models.TextField("描述", blank=True)
    mode = models.CharField("模式", max_length=16, choices=Mode.choices)
    # expose 模式:绑定的平台脚本
    script = models.ForeignKey(
        Script,
        verbose_name="绑定脚本",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="endpoints",
    )
    # monitor 模式:外部接口地址
    method = models.CharField("HTTP 方法", max_length=16, default="GET")
    url = models.CharField("外部 URL", max_length=255, blank=True)
    # 认证(仅 expose 模式生效)
    auth_type = models.CharField(
        "认证方式", max_length=16, choices=AuthType.choices, default=AuthType.NONE
    )
    auth_key_hash = models.CharField("API Key 哈希", max_length=255, blank=True, editable=False)
    status = models.CharField(
        "状态",
        max_length=16,
        choices=[("enabled", "启用"), ("disabled", "停用")],
        default="disabled",
        db_index=True,
    )
    timeout = models.PositiveIntegerField("超时(秒)", default=10)
    version = models.CharField("版本", max_length=32, default="v1")
    params_schema = models.JSONField("入参定义", default=list, blank=True)
    business = models.ForeignKey(
        Business, verbose_name="业务线", on_delete=models.PROTECT, related_name="endpoints"
    )
    project = models.ForeignKey(
        Project,
        verbose_name="项目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="endpoints",
    )
    environment = models.ForeignKey(
        Environment,
        verbose_name="环境",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="endpoints",
    )
    # 健康统计(monitor 滚动窗口,由巡检任务维护)
    health_status = models.CharField(
        "健康状态", max_length=16, choices=HealthStatus.choices, default=HealthStatus.UNKNOWN
    )
    avg_response_ms = models.FloatField("平均响应(毫秒)", null=True, blank=True)
    error_rate = models.FloatField("错误率", null=True, blank=True)
    call_count = models.PositiveIntegerField("窗口内调用次数", default=0)
    last_check_at = models.DateTimeField("最近检查时间", null=True, blank=True)

    class Meta:
        verbose_name = "HTTP 接口"
        verbose_name_plural = verbose_name
        permissions = [
            ("view_endpoint", "可以查看接口"),
            ("create_endpoint", "可以创建接口"),
            ("update_endpoint", "可以修改接口"),
            ("delete_endpoint", "可以删除接口"),
            ("execute_endpoint", "可以调用接口"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"], name="uniq_endpoint_code_in_business"
            )
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.name}({self.code})"

    def set_api_key(self, plain_key: str) -> None:
        """写入 API Key 哈希(明文不落库)。"""
        from django.contrib.auth.hashers import make_password

        self.auth_key_hash = make_password(plain_key)

    def verify_api_key(self, plain_key: str) -> bool:
        if not self.auth_key_hash or not plain_key:
            return False
        from django.contrib.auth.hashers import check_password

        return check_password(plain_key, self.auth_key_hash)


class EndpointCallLog(BaseModel):
    """接口调用记录:expose 调用与 monitor 探测统一记录。"""

    endpoint = models.ForeignKey(
        HttpEndpoint, verbose_name="接口", on_delete=models.CASCADE, related_name="call_logs"
    )
    mode = models.CharField("模式", max_length=16, choices=HttpEndpoint.Mode.choices)
    method = models.CharField("HTTP 方法", max_length=16, default="GET")
    url = models.CharField("URL", max_length=255, blank=True)
    status_code = models.IntegerField("HTTP 状态码", null=True, blank=True)
    response_ms = models.IntegerField("响应时间(毫秒)", null=True, blank=True)
    success = models.BooleanField("是否成功", default=False)
    error_message = models.TextField("错误信息", blank=True)
    request_id = models.CharField("请求 ID", max_length=36, blank=True, db_index=True)
    caller = models.CharField("调用方", max_length=64, blank=True)

    class Meta:
        verbose_name = "接口调用记录"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["endpoint", "-created_at"]),
            models.Index(fields=["success", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.endpoint.code} {self.status_code} {self.response_ms}ms"

    @property
    def created_at_local(self):
        return timezone.localtime(self.created_at) if self.created_at else None
