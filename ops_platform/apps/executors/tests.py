"""executors 测试:Docker 命令构造/超时清理、注册表解析、资源限制、执行链路。"""
import io
import subprocess
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase

from ops_platform.apps.accounts.models import Business, Environment, User
from ops_platform.apps.executions.models import Execution
from ops_platform.apps.scripts.models import Script, ScriptVersion

from .docker import DockerExecutor
from .local import LocalProcessExecutor
from .registry import ExecutorRegistry


class FakeProc:
    """模拟 subprocess.Popen:空输出,可控退出码与超时。"""

    def __init__(self, returncode=0, timeout=False):
        self.returncode = returncode
        self.stdout = io.StringIO("")
        self._timeout = timeout
        self._waited = 0

    def wait(self, timeout=None):
        if self._timeout and self._waited == 0:
            self._waited = 1
            raise subprocess.TimeoutExpired("docker", timeout)
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass


def make_docker_env(runner="docker:python:3.11-slim", memory=256, cpu=0.5, code="print(1)"):
    owner = User.objects.create_user("owner", "o@test.local", "owner-pass-123")
    biz = Business.objects.create(name="业务", code="biz")
    env = Environment.objects.create(name="生产", code="prod")
    script = Script.objects.create(
        name="脚本", code="sc", owner=owner, business=biz, environment=env,
        runner=runner, memory_limit_mb=memory, cpu_limit=cpu, timeout_seconds=10,
    )
    ScriptVersion.objects.create(
        script=script, version=1, code=code, is_current=True, created_by=owner
    )
    script.current_version = 1
    script.save(update_fields=["current_version"])
    execution = Execution.objects.create(
        asset_type="script", asset_id=script.pk, trigger_type="manual",
        request_id="req-d", business=biz, environment=env,
    )
    return script, execution


class DockerExecutorTests(TestCase):
    def test_run_command_with_resources(self):
        script, execution = make_docker_env()
        proc = FakeProc()
        with patch(
            "ops_platform.apps.executors.docker.subprocess.Popen", return_value=proc
        ) as mock_popen:
            result = DockerExecutor().execute(
                execution, script.current_version_obj, {"k": "v"}, timeout=10
            )
        self.assertEqual(result.status, "success")
        cmd = mock_popen.call_args.args[0]
        self.assertEqual(cmd[0], "docker")
        self.assertIn("--name", cmd)
        self.assertIn(f"ops-exec-{execution.pk}", cmd)
        self.assertIn("-m", cmd)
        self.assertIn("256m", cmd)
        self.assertIn("--cpus", cmd)
        self.assertIn("0.5", cmd)
        self.assertIn("python:3.11-slim", cmd)
        self.assertIn("-e", cmd)
        self.assertIn(f"OPS_EXECUTION_ID={execution.pk}", cmd)
        self.assertIn("-v", cmd)

    def test_no_resource_limits_when_unset(self):
        script, execution = make_docker_env(memory=None, cpu=None)
        proc = FakeProc()
        with patch(
            "ops_platform.apps.executors.docker.subprocess.Popen", return_value=proc
        ) as mock_popen:
            DockerExecutor().execute(execution, script.current_version_obj, {}, timeout=10)
        cmd = mock_popen.call_args.args[0]
        self.assertNotIn("-m", cmd)
        self.assertNotIn("--cpus", cmd)

    def test_timeout_kills_container(self):
        script, execution = make_docker_env()
        proc = FakeProc(timeout=True)
        with patch(
            "ops_platform.apps.executors.docker.subprocess.Popen", return_value=proc
        ):
            with patch(
                "ops_platform.apps.executors.docker.subprocess.run"
            ) as mock_run:
                result = DockerExecutor().execute(
                    execution, script.current_version_obj, {}, timeout=1
                )
        self.assertEqual(result.status, "timeout")
        kill_cmd = mock_run.call_args.args[0]
        self.assertIn("docker", kill_cmd)
        self.assertIn("kill", kill_cmd)
        self.assertIn(f"ops-exec-{execution.pk}", kill_cmd)

    def test_invalid_runner(self):
        script, execution = make_docker_env(runner="docker:")
        result = DockerExecutor().execute(
            execution, script.current_version_obj, {}, timeout=10
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("格式错误", result.error_message)


class RegistryTests(TestCase):
    def test_resolve_executors(self):
        self.assertIsInstance(ExecutorRegistry.get("docker:python:3.11"), DockerExecutor)
        self.assertIsInstance(ExecutorRegistry.get("python"), LocalProcessExecutor)
        with self.assertRaises(NotImplementedError):
            ExecutorRegistry.get("agent:node-01")


class DockerWiringTests(TransactionTestCase):
    """execute_asset 全链路走 Docker 执行器(mock docker CLI)。"""

    def test_execute_asset_with_docker_runner(self):
        script, execution = make_docker_env()
        proc = FakeProc()
        with patch(
            "ops_platform.apps.executors.docker.subprocess.Popen", return_value=proc
        ):
            from ops_platform.apps.executions.tasks import execute_asset

            result = execute_asset(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(execution.status, "success")
        self.assertEqual(execution.result_code, 0)
