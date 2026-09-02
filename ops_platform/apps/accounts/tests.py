"""accounts 单元测试:登录、RBAC 权限、数据范围过滤。"""
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory, APITestCase, force_authenticate
from rest_framework.views import APIView

from .models import Business, DataScope, Environment, Project, Role, User
from .permissions import HasPerm
from .scope import build_scope_q, get_user_scopes, scope_queryset


class ScopedAsset(models.Model):
    """测试专用资产模型:带数据范围三字段,模拟未来 Script/ScheduleTask 等资产。"""

    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE)
    environment = models.ForeignKey(
        Environment, null=True, blank=True, on_delete=models.CASCADE
    )
    name = models.CharField(max_length=64)

    class Meta:
        app_label = "accounts"


# ---------------------------------------------------------------------------
# 数据范围过滤
# ---------------------------------------------------------------------------
class ScopeFilterTests(TransactionTestCase):
    """使用 TransactionTestCase:SQLite 下 TestCase 事务中无法用 schema_editor 建临时表。

    动态模型表不受 Django flush 管理,每个测试结束后手动清理。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            editor.create_model(ScopedAsset)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            editor.delete_model(ScopedAsset)

    def tearDown(self):
        ScopedAsset.objects.all().delete()

    def setUp(self):
        self.b1 = Business.objects.create(name="业务一", code="b1")
        self.b2 = Business.objects.create(name="业务二", code="b2")
        self.p1 = Project.objects.create(business=self.b1, name="项目一", code="p1")
        self.p2 = Project.objects.create(business=self.b1, name="项目二", code="p2")
        self.p3 = Project.objects.create(business=self.b2, name="项目三", code="p3")
        self.e1 = Environment.objects.create(name="开发", code="dev")
        self.e2 = Environment.objects.create(name="生产", code="prod")

        self.assets = {
            "a1": ScopedAsset.objects.create(
                business=self.b1, project=self.p1, environment=self.e1, name="a1"
            ),
            "a2": ScopedAsset.objects.create(
                business=self.b1, project=self.p1, environment=self.e2, name="a2"
            ),
            "a3": ScopedAsset.objects.create(
                business=self.b1, project=self.p2, environment=self.e1, name="a3"
            ),
            "a4": ScopedAsset.objects.create(
                business=self.b2, project=self.p3, environment=self.e1, name="a4"
            ),
            "a5": ScopedAsset.objects.create(
                business=self.b1, project=self.p1, environment=None, name="a5"
            ),
        }
        self.admin = User.objects.create_superuser(
            "admin", "admin@test.local", "admin-pass-123"
        )
        self.user = User.objects.create_user(
            "alice", "alice@test.local", "alice-pass-123"
        )
        self.role = Role.objects.create(name="业务一运营", code="b1_ops")
        self.user.roles.add(self.role)

    def _names(self, qs):
        return sorted(qs.values_list("name", flat=True))

    def test_superuser_ignores_scope(self):
        self.assertEqual(
            self._names(scope_queryset(ScopedAsset.objects.all(), self.admin)),
            ["a1", "a2", "a3", "a4", "a5"],
        )
        self.assertIsNone(get_user_scopes(self.admin))

    def test_user_without_scope_sees_nothing(self):
        nobody = User.objects.create_user("bob", "bob@test.local", "bob-pass-123")
        self.assertEqual(self._names(scope_queryset(ScopedAsset.objects.all(), nobody)), [])

    def test_scope_business_all(self):
        DataScope.objects.create(role=self.role, business=self.b1)
        self.assertEqual(
            self._names(scope_queryset(ScopedAsset.objects.all(), self.user)),
            ["a1", "a2", "a3", "a5"],
        )

    def test_scope_project_all_environments(self):
        DataScope.objects.create(role=self.role, business=self.b1, project=self.p1)
        self.assertEqual(
            self._names(scope_queryset(ScopedAsset.objects.all(), self.user)),
            ["a1", "a2", "a5"],
        )

    def test_scope_environment_across_projects(self):
        DataScope.objects.create(role=self.role, business=self.b1, environment=self.e1)
        self.assertEqual(
            self._names(scope_queryset(ScopedAsset.objects.all(), self.user)),
            ["a1", "a3"],
        )

    def test_scope_full_combination(self):
        DataScope.objects.create(
            role=self.role, business=self.b1, project=self.p1, environment=self.e1
        )
        self.assertEqual(
            self._names(scope_queryset(ScopedAsset.objects.all(), self.user)), ["a1"]
        )

    def test_role_and_user_scopes_union(self):
        DataScope.objects.create(role=self.role, business=self.b1)
        DataScope.objects.create(user=self.user, business=self.b2, project=self.p3)
        self.assertEqual(
            self._names(scope_queryset(ScopedAsset.objects.all(), self.user)),
            ["a1", "a2", "a3", "a4", "a5"],
        )

    def test_unassigned_environment_requires_full_env_scope(self):
        # a5 环境为空,只有"该业务全部环境"或"该业务+项目全部环境"授权可见
        DataScope.objects.create(role=self.role, business=self.b1, environment=self.e1)
        self.assertNotIn("a5", self._names(scope_queryset(ScopedAsset.objects.all(), self.user)))

    def test_build_scope_q_empty_set_rejects_all(self):
        self.assertEqual(
            list(ScopedAsset.objects.filter(build_scope_q(set()))), []
        )


# ---------------------------------------------------------------------------
# RBAC 操作权限
# ---------------------------------------------------------------------------
class PermView(APIView):
    required_permission = "execute_script"
    permission_classes = [permissions.IsAuthenticated, HasPerm]

    def get(self, request):
        return Response({"ok": True})


class HasPermTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user("carol", "carol@test.local", "carol-pass-123")
        self.role = Role.objects.create(name="脚本执行者", code="script_runner")
        self.user.roles.add(self.role)

    def _call(self, user):
        request = self.factory.get("/fake/")
        force_authenticate(request, user=user)
        return PermView.as_view()(request)

    def test_user_with_perm_can_access(self):
        perm = Permission.objects.create(
            codename="execute_script",
            name="可以执行脚本",
            content_type=ContentType.objects.get_for_model(Role),
        )
        self.role.permissions.add(perm)
        self.assertIn("execute_script", self.user.all_permission_codenames())
        response = self._call(self.user)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_user_without_perm_denied(self):
        response = self._call(self.user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_bypasses_perm(self):
        admin = User.objects.create_superuser("root", "root@test.local", "root-pass-123")
        self.assertEqual(self._call(admin).status_code, status.HTTP_200_OK)

    def test_disabled_role_perm_not_effective(self):
        perm = Permission.objects.create(
            codename="execute_script",
            name="可以执行脚本",
            content_type=ContentType.objects.get_for_model(Role),
        )
        self.role.permissions.add(perm)
        self.role.enabled = False
        self.role.save()
        # all_permission_codenames 仅聚合启用角色的权限
        self.assertNotIn("execute_script", self.user.all_permission_codenames())
        self.assertEqual(self._call(self.user).status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 登录 / 当前用户
# ---------------------------------------------------------------------------
class AuthApiTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            "dave", "dave@test.local", "dave-pass-123", display_name="戴夫"
        )

    def test_login_success_returns_tokens_and_user(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "dave", "password": "dave-pass-123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["username"], "dave")

    def test_login_wrong_password_rejected(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "dave", "password": "wrong-pass"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_requires_auth(self):
        response = self.client.get(reverse("accounts:me"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_profile_with_token(self):
        token_response = self.client.post(
            reverse("accounts:login"),
            {"username": "dave", "password": "dave-pass-123"},
            format="json",
        )
        token = token_response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.get(reverse("accounts:me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "dave")
        self.assertEqual(response.data["display_name"], "戴夫")
