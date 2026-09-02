"""executions 测试:状态机、真实执行(成功/失败/超时/敏感过滤/SDK)、执行历史 API。"""
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from ops_platform.apps.accounts.models import Business, DataScope, Environment, User
from ops_platform.apps.scripts.models import Script, ScriptVersion

from .models import Execution
from .state import InvalidTransitionError, assert_transition, can_transition
from .tasks import execute_asset


def make_script_env(**kwargs):
    """创建最小脚本资产环境,返回 (script, execution)。"""
    owner = kwargs.pop("owner", None) or User.objects.create_user(
        "owner", "owner@test.local", "owner-pass-123"
    )
    biz = kwargs.pop("biz", None) or Business.objects.create(name="业务", code="biz")
    env = kwargs.pop("env", None) or Environment.objects.create(name="生产", code="prod")
    code = kwargs.pop("code", "print('hello')")
    timeout = kwargs.pop("timeout", 10)
    params = kwargs.pop("params", {"host": "h1"})
    runner = kwargs.pop("runner", "python")

    script = Script.objects.create(
        name="测试脚本",
        code="t_script",
        owner=owner,
        business=biz,
        environment=env,
        runner=runner,
        timeout_seconds=timeout,
    )
    ScriptVersion.objects.create(
        script=script, version=1, code=code, is_current=True, created_by=owner
    )
    script.current_version = 1
    script.save(update_fields=["current_version"])
    execution = Execution.objects.create(
        asset_type=Execution.AssetType.SCRIPT,
        asset_id=script.pk,
        trigger_type=Execution.TriggerType.MANUAL,
        trigger_user=owner,
        params=params,
        request_id="req-1",
        business=biz,
        environment=env,
    )
    return script, execution


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------
class StateTransitionTests(TestCase):
    def test_valid_transitions(self):
        execution = Execution(status=Execution.Status.PENDING)
        assert_transition(execution, Execution.Status.RUNNING)
        assert_transition(execution, Execution.Status.SUCCESS)
        self.assertEqual(execution.status, Execution.Status.SUCCESS)

    def test_invalid_transitions(self):
        execution = Execution(status=Execution.Status.PENDING)
        with self.assertRaises(InvalidTransitionError):
            assert_transition(execution, Execution.Status.SUCCESS)
        self.assertFalse(can_transition(Execution.Status.SUCCESS, Execution.Status.RUNNING))
        # 终态不可再迁移
        execution.status = Execution.Status.SUCCESS
        self.assertFalse(can_transition(execution.status, Execution.Status.FAILED))


# ---------------------------------------------------------------------------
# 真实执行链路(本地进程,直接调用 Celery 任务函数)
# ---------------------------------------------------------------------------
class ExecuteTaskTests(TransactionTestCase):
    """使用 TransactionTestCase:子进程日志采集线程需要独立 DB 连接,
    TestCase 事务隔离会导致采集线程读不到未提交数据,外键写入失败。"""
    def test_success(self):
        _, execution = make_script_env(code="print('hello'); import time; time.sleep(0.05)")
        result = execute_asset(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(result["status"], Execution.Status.SUCCESS)
        self.assertEqual(execution.status, Execution.Status.SUCCESS)
        self.assertEqual(execution.result_code, 0)
        self.assertGreaterEqual(execution.duration_ms, 0)
        messages = " ".join(execution.logs.values_list("message", flat=True))
        self.assertIn("hello", messages)

    def test_failed_exit_code(self):
        _, execution = make_script_env(code="import sys; sys.exit(3)")
        execute_asset(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(execution.status, Execution.Status.FAILED)
        self.assertEqual(execution.result_code, 3)
        self.assertIn("退出码 3", execution.error_message)

    def test_timeout_kills_process(self):
        _, execution = make_script_env(code="import time; time.sleep(60)", timeout=1)
        execute_asset(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(execution.status, Execution.Status.TIMEOUT)
        self.assertIn("超时", execution.error_message)
        self.assertTrue(execution.logs.filter(level="ERROR").exists())

    def test_sensitive_keyword_masked(self):
        _, execution = make_script_env(code="print('password=supersecret')")
        execute_asset(execution.pk)
        messages = list(execution.logs.values_list("message", flat=True))
        self.assertTrue(any("password=***" in m for m in messages), messages)
        self.assertFalse(any("supersecret" in m for m in messages), messages)

    def test_sdk_structured_log(self):
        code = (
            "import ops_sdk\n"
            'ops_sdk.log("处理完成", level="INFO", target="x")\n'
            'print("普通输出")\n'
        )
        _, execution = make_script_env(code=code)
        execute_asset(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(execution.status, Execution.Status.SUCCESS)
        structured = execution.logs.filter(message="处理完成").first()
        self.assertIsNotNone(structured)
        self.assertEqual(structured.extra, {"target": "x"})
        self.assertEqual(structured.request_id, "req-1")

    def test_sdk_secret_marked_masked(self):
        code = (
            "import ops_sdk\n"
            'token = ops_sdk.mark_secret("tok-12345")\n'
            'ops_sdk.log(f"使用 token={token}")\n'
        )
        _, execution = make_script_env(code=code)
        execute_asset(execution.pk)
        messages = list(execution.logs.values_list("message", flat=True))
        self.assertTrue(any("使用 token=***" in m for m in messages), messages)
        self.assertFalse(any("tok-12345" in m for m in messages), messages)

    def test_script_not_found(self):
        _, execution = make_script_env()
        execution.asset_id = 999999
        execution.save(update_fields=["asset_id"])
        execute_asset(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(execution.status, Execution.Status.FAILED)
        self.assertIn("不存在", execution.error_message)

    def test_idempotent_non_pending_skip(self):
        _, execution = make_script_env()
        execution.status = Execution.Status.SUCCESS
        execution.save(update_fields=["status"])
        result = execute_asset(execution.pk)
        self.assertTrue(result["skipped"])


# ---------------------------------------------------------------------------
# 执行历史 API
# ---------------------------------------------------------------------------
class ExecutionApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@test.local", "admin-pass-123")
        self.client.force_authenticate(self.admin)
        _, self.execution = make_script_env()
        self.execution.status = Execution.Status.SUCCESS
        self.execution.save(update_fields=["status"])

    def test_list_and_filter(self):
        resp = self.client.get("/api/executions/?asset_type=script&status=success")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)

    def test_detail_contains_params(self):
        resp = self.client.get(f"/api/executions/{self.execution.pk}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["params"], {"host": "h1"})
        self.assertIn("asset_name", resp.data)

    def test_logs_endpoint(self):
        from ops_platform.apps.logs.services import add_log

        add_log(self.execution, "第一行", level="INFO")
        add_log(self.execution, "第二行", level="WARNING")
        resp = self.client.get(f"/api/executions/{self.execution.pk}/logs/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 2)

    def test_list_respects_data_scope(self):
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        from ops_platform.apps.accounts.models import Role

        user = User.objects.create_user("nobody", "n@test.local", "nobody-pass-123")
        role = Role.objects.create(name="查看者", code="viewer")
        # 复用 Execution 模型默认权限 view_execution(避免与模型迁移生成的权限冲突)
        perm = Permission.objects.get(
            codename="view_execution",
            content_type=ContentType.objects.get_for_model(Execution),
        )
        role.permissions.add(perm)
        user.roles.add(role)
        self.client.force_authenticate(user)
        resp = self.client.get("/api/executions/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 0)
        DataScope.objects.create(user=user, business=self.execution.business)
        resp = self.client.get("/api/executions/")
        self.assertEqual(resp.data["count"], 1)
