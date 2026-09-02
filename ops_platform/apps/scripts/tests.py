"""scripts 测试:参数校验、版本管理、API(权限/数据范围/手工执行)。"""
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from ops_platform.apps.accounts.models import (
    Business,
    DataScope,
    Environment,
    Project,
    Role,
    User,
)

from .models import Script, ScriptVersion
from .params import validate_params, validate_schema


def make_user(username="ops", password="ops-pass-123", **kwargs):
    return User.objects.create_user(username, f"{username}@test.local", password, **kwargs)


# ---------------------------------------------------------------------------
# 参数 schema 校验
# ---------------------------------------------------------------------------
class ParamsValidationTests(TestCase):
    def test_required_and_defaults(self):
        schema = [
            {"name": "host", "type": "string", "required": True},
            {"name": "count", "type": "integer", "default": 10},
        ]
        normalized, errors = validate_params(schema, {"host": "h1"})
        self.assertEqual(errors, [])
        self.assertEqual(normalized, {"host": "h1", "count": 10})

    def test_missing_required(self):
        schema = [{"name": "host", "type": "string", "required": True}]
        _, errors = validate_params(schema, {})
        self.assertEqual(errors, ["缺少必填参数: host"])

    def test_integer_coercion_and_bounds(self):
        schema = [{"name": "n", "type": "integer", "min": 1, "max": 10}]
        self.assertEqual(validate_params(schema, {"n": "5"}), ({"n": 5}, []))
        _, errors = validate_params(schema, {"n": 99})
        self.assertEqual(errors, ["参数 n 不能大于 10"])

    def test_boolean_coercion(self):
        schema = [{"name": "dry", "type": "boolean"}]
        self.assertEqual(validate_params(schema, {"dry": "true"})[0], {"dry": True})
        _, errors = validate_params(schema, {"dry": "maybe"})
        self.assertTrue(errors)

    def test_schema_self_validation(self):
        self.assertEqual(validate_schema([{"name": "a", "type": "string"}]), [])
        self.assertTrue(validate_schema([{"name": "a", "type": "datetime"}]))
        self.assertTrue(validate_schema([{"name": "a"}, {"name": "a"}]))


# ---------------------------------------------------------------------------
# 文件集 + 环境变量:真实执行(子进程 import 附加文件、读取注入的环境变量)
# ---------------------------------------------------------------------------
class ScriptFilesAndEnvTests(TransactionTestCase):
    def _make_env(self):
        owner = make_user("owner", "owner-pass-123")
        biz = Business.objects.create(name="业务", code="biz")
        env = Environment.objects.create(name="生产", code="prod")
        script = Script.objects.create(
            name="文件集脚本", code="multi_file", owner=owner,
            business=biz, environment=env, timeout_seconds=10,
        )
        ScriptVersion.objects.create(
            script=script, version=1, code="", is_current=True, created_by=owner
        )
        script.current_version = 1
        script.save(update_fields=["current_version"])
        return script

    def test_execute_with_files_and_env_vars(self):
        from ops_platform.apps.executions.models import Execution
        from ops_platform.apps.executions.tasks import execute_asset

        script = self._make_env()
        # 主代码 import 文件集模块 + 读取注入的环境变量
        code = (
            "from utils.helper import greet\n"
            "import os\n"
            "print(greet(os.getenv('DB_HOST', 'none')))\n"
            "print('port=' + os.getenv('DB_PORT', 'none'))\n"
        )
        version = script.versions.get(version=1)
        version.code = code
        version.files = [
            {"path": "utils/helper.py", "content": "def greet(name):\n    return 'hello ' + name\n"}
        ]
        version.save(update_fields=["code", "files"])
        script.set_env_vars({"DB_HOST": "db-internal", "DB_PORT": "5432"})
        script.save(update_fields=["env_vars"])

        execution = Execution.objects.create(
            asset_type=Execution.AssetType.SCRIPT, asset_id=script.pk,
            trigger_type=Execution.TriggerType.MANUAL, request_id="req-files",
            business=script.business, environment=script.environment,
        )
        result = execute_asset(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(result["status"], Execution.Status.SUCCESS)
        messages = " ".join(execution.logs.values_list("message", flat=True))
        self.assertIn("hello db-internal", messages)
        self.assertIn("port=5432", messages)

    def test_fallback_to_script_files_when_version_empty(self):
        from ops_platform.apps.executions.models import Execution
        from ops_platform.apps.executions.tasks import execute_asset

        script = self._make_env()
        version = script.versions.get(version=1)
        version.code = "from utils.config import greeting\nprint(greeting())\n"
        version.files = []  # 版本快照为空 → 应回退脚本当前 files
        version.save(update_fields=["code", "files"])
        script.files = [
            {"path": "utils/config.py", "content": "def greeting():\n    return 'hello fallback'\n"}
        ]
        script.save(update_fields=["files"])

        execution = Execution.objects.create(
            asset_type=Execution.AssetType.SCRIPT, asset_id=script.pk,
            trigger_type=Execution.TriggerType.MANUAL, request_id="req-fallback",
            business=script.business, environment=script.environment,
        )
        result = execute_asset(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(result["status"], Execution.Status.SUCCESS)
        messages = " ".join(execution.logs.values_list("message", flat=True))
        self.assertIn("hello fallback", messages)

    def test_path_traversal_blocked(self):
        script = self._make_env()
        version = script.versions.get(version=1)
        version.code = "print('ok')\n"
        version.files = [{"path": "../../evil.py", "content": "print('pwned')\n"}]
        version.save(update_fields=["code", "files"])
        from ops_platform.apps.executors.local import _write_files
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            _write_files(Path(tmp), version)
            self.assertFalse((Path(tmp) / ".." / "evil.py").exists())


# ---------------------------------------------------------------------------
# 脚本 API:CRUD / 版本 / 启停 / 执行 / 数据范围
# ---------------------------------------------------------------------------
class ScriptApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@test.local", "admin-pass-123")
        self.client.force_authenticate(self.admin)
        self.biz = Business.objects.create(name="业务", code="biz")
        self.proj = Project.objects.create(business=self.biz, name="项目", code="p1")
        self.env = Environment.objects.create(name="生产", code="prod")

    def _create_script(self, code="print('hi')", **kwargs):
        data = {
            "name": "数据同步",
            "code": "data_sync",
            "business": self.biz.pk,
            "project": self.proj.pk,
            "environment": self.env.pk,
            "params_schema": [{"name": "host", "type": "string", "required": True}],
            "source_code": code,
        }
        data.update(kwargs)
        return self.client.post("/api/scripts/", data, format="json")

    def test_create_script_creates_v1(self):
        resp = self._create_script()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        script = Script.objects.get(pk=resp.data["id"])
        self.assertEqual(script.current_version, 1)
        self.assertTrue(script.versions.get(version=1).is_current)
        self.assertEqual(script.versions.get(version=1).code, "print('hi')")

    def test_create_with_bad_schema_rejected(self):
        resp = self._create_script(params_schema=[{"name": "a", "type": "nope"}])
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_resource_limits(self):
        resp = self._create_script(
            runner="docker:python:3.11", memory_limit_mb=512, cpu_limit=0.5
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        script = Script.objects.get(pk=resp.data["id"])
        self.assertEqual(script.memory_limit_mb, 512)
        self.assertEqual(script.cpu_limit, 0.5)

    def test_create_with_files_and_env_vars(self):
        resp = self._create_script(
            files=[{"path": "utils/x.py", "content": "VALUE=1\n"}],
            env_vars={"DB_HOST": "db-internal", "DB_PASSWORD": "secret-p1"},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        script = Script.objects.get(pk=resp.data["id"])
        self.assertEqual(script.files[0]["path"], "utils/x.py")
        # env_vars 加密落库:敏感键为 enc: 前缀,明文不出现
        self.assertTrue(script.env_vars["DB_PASSWORD"].startswith("enc:"))
        self.assertNotIn("secret-p1", script.env_vars["DB_PASSWORD"])
        # 详情只回显键名 + ***,不回显明文
        detail = self.client.get(f"/api/scripts/{script.pk}/").data
        self.assertEqual(detail["env_vars"], {"DB_HOST": "***", "DB_PASSWORD": "***"})
        # 解密后能还原
        self.assertEqual(script.get_env_vars()["DB_HOST"], "db-internal")

    def test_create_version_and_rollback(self):
        sid = self._create_script(code="v1").data["id"]
        resp = self.client.post(
            f"/api/scripts/{sid}/create_version/",
            {"code": "v2", "changelog": "更新"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        script = Script.objects.get(pk=sid)
        self.assertEqual(script.current_version, 2)
        self.assertEqual(script.current_version_obj.code, "v2")
        self.assertFalse(script.versions.get(version=1).is_current)

        resp = self.client.post(f"/api/scripts/{sid}/versions/1/rollback/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        script.refresh_from_db()
        self.assertEqual(script.current_version, 1)
        self.assertTrue(script.versions.get(version=1).is_current)
        self.assertFalse(script.versions.get(version=2).is_current)

    def test_enable_disable(self):
        sid = self._create_script().data["id"]
        self.assertEqual(self.client.post(f"/api/scripts/{sid}/enable/").data["status"], "enabled")
        self.assertEqual(self.client.post(f"/api/scripts/{sid}/disable/").data["status"], "disabled")

    def test_list_respects_data_scope(self):
        self._create_script()
        user = make_user("nobody")
        role = Role.objects.create(name="查看者", code="viewer")
        # 复用 Script 模型默认权限 view_script(避免与模型迁移生成的权限冲突)
        perm = Permission.objects.get(
            codename="view_script",
            content_type=ContentType.objects.get_for_model(Script),
        )
        role.permissions.add(perm)
        user.roles.add(role)
        self.client.force_authenticate(user)
        resp = self.client.get("/api/scripts/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 0)
        DataScope.objects.create(user=user, business=self.biz)
        resp = self.client.get("/api/scripts/")
        self.assertEqual(resp.data["count"], 1)

    def test_execute_disabled_script_rejected(self):
        sid = self._create_script().data["id"]
        resp = self.client.post(
            f"/api/scripts/{sid}/execute/", {"params": {"host": "x"}}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_execute_enabled_returns_202_and_validates_params(self):
        from unittest.mock import patch

        sid = self._create_script().data["id"]
        self.client.post(f"/api/scripts/{sid}/enable/")
        # mock 任务投递,避免测试依赖 Redis
        with patch("ops_platform.apps.scripts.views.execute_asset.delay") as mock_delay:
            resp = self.client.post(
                f"/api/scripts/{sid}/execute/", {"params": {"host": "h1"}}, format="json"
            )
            mock_delay.assert_called_once()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.data)
        self.assertIn("execution_id", resp.data)
        # 缺少必填参数 → 400
        resp = self.client.post(f"/api/scripts/{sid}/execute/", {"params": {}}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_execute_requires_permission(self):
        user = make_user("runner")
        role = Role.objects.create(name="执行", code="exec")
        user.roles.add(role)
        DataScope.objects.create(user=user, business=self.biz)
        sid = self._create_script().data["id"]
        self.client.post(f"/api/scripts/{sid}/enable/")
        self.client.force_authenticate(user)
        resp = self.client.post(
            f"/api/scripts/{sid}/execute/", {"params": {"host": "h"}}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_execute_out_of_scope_denied(self):
        other_biz = Business.objects.create(name="其他业务", code="other")
        sid = self._create_script(business=other_biz.pk, project=None, environment=None).data["id"]
        user = make_user("scoped")
        DataScope.objects.create(user=user, business=self.biz)
        self.client.force_authenticate(user)
        resp = self.client.post(
            f"/api/scripts/{sid}/execute/", {"params": {"host": "h"}}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
