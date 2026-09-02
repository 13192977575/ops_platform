"""脚本资产模型:登记、参数 schema、版本快照(D1:平台内维护 + 版本快照,预留 Git)。"""
from django.conf import settings
from django.db import models

from ops_platform.apps.accounts.models import Business, Environment, Project
from ops_platform.apps.common.models import BaseModel


class Script(BaseModel):
    """脚本登记。执行时使用 current_version 对应的 ScriptVersion 快照。"""

    class Status(models.TextChoices):
        ENABLED = "enabled", "启用"
        DISABLED = "disabled", "停用"

    class SourceType(models.TextChoices):
        INLINE = "inline", "平台内代码"
        # GIT = "git", "Git 仓库"  # D1 预留:二期支持 Git 接入

    name = models.CharField("脚本名称", max_length=64)
    code = models.CharField("脚本编码", max_length=32, help_text="业务线内唯一,如 data_sync")
    description = models.TextField("描述", blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="负责人",
        on_delete=models.PROTECT,
        related_name="owned_scripts",
    )
    business = models.ForeignKey(
        Business, verbose_name="业务线", on_delete=models.PROTECT, related_name="scripts"
    )
    project = models.ForeignKey(
        Project,
        verbose_name="项目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="scripts",
    )
    environment = models.ForeignKey(
        Environment,
        verbose_name="环境",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="scripts",
    )
    runner = models.CharField(
        "执行器/解释器",
        max_length=64,
        default="python",
        help_text="python(默认,使用平台解释器)或解释器绝对路径;docker:xxx 二期支持",
    )
    source_type = models.CharField(
        "代码来源",
        max_length=16,
        choices=SourceType.choices,
        default=SourceType.INLINE,
    )
    params_schema = models.JSONField(
        "参数定义", default=list, blank=True, help_text="参数 schema 列表,见 scripts/params.py"
    )
    files = models.JSONField(
        "文件集", default=list, blank=True,
        help_text="附加文件:[{\"path\": \"utils/db.py\", \"content\": \"...\"}],主代码在版本 code 中",
    )
    env_vars = models.JSONField(
        "环境变量", default=dict, blank=True,
        help_text="敏感键加密存储,执行时注入 os.environ;读取不回显明文",
    )
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.DISABLED, db_index=True
    )
    current_version = models.PositiveIntegerField("当前版本", default=0)
    timeout_seconds = models.PositiveIntegerField("超时(秒)", default=300)
    memory_limit_mb = models.PositiveIntegerField(
        "内存限制(MB)", null=True, blank=True, help_text="为空不限制;Docker 用 -m,本地进程用 RLIMIT_AS(POSIX)"
    )
    cpu_limit = models.FloatField(
        "CPU 限制(核)", null=True, blank=True, help_text="为空不限制;Docker 用 --cpus,本地进程不应用"
    )
    tags = models.JSONField("标签", default=list, blank=True)

    class Meta:
        verbose_name = "脚本"
        verbose_name_plural = verbose_name
        permissions = [
            ("create_script", "可以创建脚本"),
            ("update_script", "可以修改脚本"),
            ("execute_script", "可以执行脚本"),
            # view_script / delete_script 使用模型默认权限(命名恰好匹配)
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"], name="uniq_script_code_in_business"
            )
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.name}({self.code})"

    def set_env_vars(self, plain_config: dict) -> None:
        """加密敏感键后写入环境变量。"""
        from ops_platform.apps.common.crypto import encrypt_config

        self.env_vars = encrypt_config(plain_config)

    def get_env_vars(self) -> dict:
        """返回解密后的明文环境变量(供执行时注入)。"""
        from ops_platform.apps.common.crypto import decrypt_config

        return decrypt_config(self.env_vars)

    @property
    def current_version_obj(self):
        return self.versions.filter(version=self.current_version).first()


class ScriptVersion(BaseModel):
    """脚本版本快照:创建/更新代码时生成新版本,执行使用 is_current 版本。"""

    script = models.ForeignKey(
        Script, verbose_name="所属脚本", on_delete=models.CASCADE, related_name="versions"
    )
    version = models.PositiveIntegerField("版本号")
    code = models.TextField("脚本代码")
    files = models.JSONField("文件集快照", default=list, blank=True)
    env_vars = models.JSONField("环境变量快照", default=dict, blank=True)
    params_schema = models.JSONField("参数定义快照", default=list, blank=True)
    changelog = models.CharField("变更说明", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="创建人",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_script_versions",
    )
    is_current = models.BooleanField("当前版本", default=False)

    class Meta:
        verbose_name = "脚本版本"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=["script", "version"], name="uniq_script_version"
            )
        ]
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"{self.script.code} v{self.version}"

    def get_env_vars(self) -> dict:
        """返回解密后的环境变量快照(供执行时注入)。"""
        from ops_platform.apps.common.crypto import decrypt_config

        return decrypt_config(self.env_vars)
