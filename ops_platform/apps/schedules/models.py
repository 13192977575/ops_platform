"""定时任务模型:业务配置 + django-celery-beat PeriodicTask 调度实体。

- 调度方式二选一:cron 表达式(标准 5 段)或周期执行(秒),由 CheckConstraint 保证互斥;
- periodic_task 与 django-celery-beat 的 PeriodicTask 一一对应,由信号同步(创建/启停/删除);
- 冗余统计:last_run_at / consecutive_failures 在执行结束后更新;
  next_run_at 由 Beat 调度器维护,序列化时从 periodic_task 读取。
"""
from django.conf import settings
from django.db import models
from django_celery_beat.models import PeriodicTask

from ops_platform.apps.accounts.models import Business, Environment, Project
from ops_platform.apps.common.models import BaseModel
from ops_platform.apps.scripts.models import Script


class ScheduleTask(BaseModel):
    class ScheduleType(models.TextChoices):
        CRON = "cron", "Cron 表达式"
        INTERVAL = "interval", "周期执行"

    name = models.CharField("任务名称", max_length=64)
    code = models.CharField("任务编码", max_length=32, help_text="业务线内唯一")
    description = models.TextField("描述", blank=True)
    script = models.ForeignKey(
        Script,
        verbose_name="执行脚本",
        on_delete=models.PROTECT,
        related_name="schedule_tasks",
    )
    schedule_type = models.CharField(
        "调度方式", max_length=16, choices=ScheduleType.choices
    )
    cron_expr = models.CharField(
        "Cron 表达式", max_length=64, blank=True, help_text="标准 5 段:分 时 日 月 周"
    )
    interval_seconds = models.PositiveIntegerField(
        "周期(秒)", null=True, blank=True
    )
    timezone = models.CharField("时区", max_length=32, default="Asia/Shanghai")
    enabled = models.BooleanField("启用", default=False)
    timeout = models.PositiveIntegerField(
        "超时(秒)", null=True, blank=True, help_text="为空则使用脚本超时"
    )
    max_retries = models.PositiveIntegerField("最大重试次数", default=0)
    retry_delay = models.PositiveIntegerField("重试间隔(秒)", default=60)
    concurrency_limit = models.PositiveIntegerField("并发上限", default=1)
    params = models.JSONField("执行参数", default=dict, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="负责人",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_schedule_tasks",
    )
    business = models.ForeignKey(
        Business, verbose_name="业务线", on_delete=models.PROTECT, related_name="schedule_tasks"
    )
    project = models.ForeignKey(
        Project,
        verbose_name="项目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="schedule_tasks",
    )
    environment = models.ForeignKey(
        Environment,
        verbose_name="环境",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="schedule_tasks",
    )
    # 冗余统计
    last_run_at = models.DateTimeField("最近执行时间", null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField("连续失败次数", default=0)
    # 调度实体(由信号维护)
    periodic_task = models.OneToOneField(
        PeriodicTask,
        verbose_name="调度实体",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="schedule_task",
    )

    class Meta:
        verbose_name = "定时任务"
        verbose_name_plural = verbose_name
        permissions = [
            ("view_schedule", "可以查看定时任务"),
            ("create_schedule", "可以创建定时任务"),
            ("update_schedule", "可以修改定时任务"),
            ("delete_schedule", "可以删除定时任务"),
            ("execute_schedule", "可以执行定时任务"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"], name="uniq_schedule_code_in_business"
            ),
            models.CheckConstraint(
                check=(
                    models.Q(
                        schedule_type="cron",
                        cron_expr__gt="",
                        interval_seconds__isnull=True,
                    )
                    | models.Q(
                        schedule_type="interval",
                        cron_expr="",
                        interval_seconds__isnull=False,
                    )
                ),
                name="schedule_type_fields_exclusive",
            ),
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.name}({self.code})"

    @property
    def effective_timeout(self) -> int:
        return self.timeout or self.script.timeout_seconds

    @property
    def next_run_at(self):
        """下一次执行时间:由 PeriodicTask 的调度实体(纯计算)得出,UTC aware。"""
        pt = self.periodic_task
        if pt is None:
            return None
        try:
            from django_celery_beat.schedulers import ModelEntry

            entry = ModelEntry(pt, app=None)
            _, next_run = entry.next()
            return next_run
        except Exception:
            return None
