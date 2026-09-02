"""用户、角色、权限与数据范围(业务/项目/环境)模型。

RBAC 分层:
1. 操作权限:Role(角色) → Permission(Django 内置权限表),User 通过 roles M2M 获得;
2. 数据范围:DataScope 授予"角色或用户"对 (business, project?, environment?) 组合的访问权,
   project / environment 为空表示该维度全部。
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from ops_platform.apps.common.models import BaseModel


class Business(BaseModel):
    """业务线:数据范围第一层维度。"""

    name = models.CharField("业务线名称", max_length=64, unique=True)
    code = models.CharField("业务线编码", max_length=32, unique=True)
    description = models.TextField("描述", blank=True)
    enabled = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "业务线"
        verbose_name_plural = verbose_name
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class Project(BaseModel):
    """项目:隶属于业务线。"""

    business = models.ForeignKey(
        Business,
        verbose_name="所属业务线",
        on_delete=models.PROTECT,
        related_name="projects",
    )
    name = models.CharField("项目名称", max_length=64)
    code = models.CharField("项目编码", max_length=32)
    description = models.TextField("描述", blank=True)
    enabled = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "项目"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"], name="uniq_project_code_in_business"
            )
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.business.name}/{self.name}"


class Environment(BaseModel):
    """环境:dev / test / prod 等。"""

    name = models.CharField("环境名称", max_length=32, unique=True)
    code = models.CharField("环境编码", max_length=16, unique=True)
    description = models.TextField("描述", blank=True)

    class Meta:
        verbose_name = "环境"
        verbose_name_plural = verbose_name
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """平台用户:扩展 Django 用户,本地认证,预留 LDAP/AD 来源标记(D8 仅认证)。"""

    class Source(models.TextChoices):
        LOCAL = "local", "本地"
        LDAP = "ldap", "LDAP/AD"

    display_name = models.CharField("显示名", max_length=64, blank=True)
    source = models.CharField(
        "认证来源",
        max_length=16,
        choices=Source.choices,
        default=Source.LOCAL,
        db_index=True,
    )
    phone = models.CharField("手机号", max_length=32, blank=True)
    roles = models.ManyToManyField(
        "Role",
        verbose_name="角色",
        blank=True,
        related_name="users",
        help_text="角色决定操作权限与角色级数据范围",
    )

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return self.display_name or self.username

    def get_display_name(self) -> str:
        return self.display_name or self.username

    def all_permission_codenames(self) -> set[str]:
        """聚合自身 + 所有角色的权限 codename(不含 Django admin 系统权限差异)。"""
        from django.contrib.auth.models import Permission

        own = Permission.objects.filter(user=self)
        via_roles = Permission.objects.filter(roles__enabled=True, roles__users=self)
        return set((own | via_roles).values_list("codename", flat=True))


class Role(BaseModel):
    """角色:承载操作权限(RBAC),并可被 DataScope 授权数据范围。"""

    name = models.CharField("角色名称", max_length=64, unique=True)
    code = models.CharField("角色编码", max_length=32, unique=True)
    description = models.TextField("描述", blank=True)
    permissions = models.ManyToManyField(
        "auth.Permission",
        verbose_name="操作权限",
        blank=True,
        related_name="roles",
    )
    enabled = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "角色"
        verbose_name_plural = verbose_name
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class DataScope(BaseModel):
    """数据范围授权:授予"角色或用户"对 (business, project?, environment?) 的访问权。

    - business 必填;
    - project / environment 为空表示该维度下全部;
    - role 与 user 二选一(约束见 Meta.constraints)。
    """

    role = models.ForeignKey(
        Role,
        verbose_name="授权角色",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="data_scopes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="授权用户",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="data_scopes",
    )
    business = models.ForeignKey(
        Business,
        verbose_name="业务线",
        on_delete=models.CASCADE,
        related_name="data_scopes",
    )
    project = models.ForeignKey(
        Project,
        verbose_name="项目",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="data_scopes",
    )
    environment = models.ForeignKey(
        Environment,
        verbose_name="环境",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="data_scopes",
    )

    class Meta:
        verbose_name = "数据范围"
        verbose_name_plural = verbose_name
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(role__isnull=False, user__isnull=True)
                    | models.Q(role__isnull=True, user__isnull=False)
                ),
                name="datascope_role_or_user_exclusive",
            ),
            models.UniqueConstraint(
                fields=["role", "business", "project", "environment"],
                name="uniq_role_datascope",
                condition=models.Q(role__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["user", "business", "project", "environment"],
                name="uniq_user_datascope",
                condition=models.Q(user__isnull=False),
            ),
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        owner = self.role or self.user
        scope = f"{self.business.name}"
        if self.project:
            scope += f"/{self.project.name}"
        if self.environment:
            scope += f"/{self.environment.name}"
        return f"{owner}: {scope}"
