"""endpoints 测试:API Key 哈希、健康统计、monitor 探测、invoke 认证、真实执行、CRUD。"""
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from ops_platform.apps.accounts.models import Business, DataScope, Environment, User
from ops_platform.apps.executions.models import Execution
from ops_platform.apps.executions.tasks import execute_asset
from ops_platform.apps.scripts.models import Script, ScriptVersion

from .models import EndpointCallLog, HttpEndpoint
from .services import probe_endpoint, update_health_stats
from .tasks import monitor_endpoints


def make_env():
    owner = User.objects.create_user("owner", "owner@test.local", "owner-pass-123")
    biz = Business.objects.create(name="业务", code="biz")
    env = Environment.objects.create(name="生产", code="prod")
    script = Script.objects.create(
        name="测试脚本", code="t_script", owner=owner, business=biz, environment=env,
        timeout_seconds=10,
    )
    ScriptVersion.objects.create(
        script=script, version=1, code="print('ok'); import time; time.sleep(0.05)",
        is_current=True, created_by=owner,
    )
    script.current_version = 1
    script.save(update_fields=["current_version"])
    return owner, biz, env, script


def make_endpoint(biz, env, script=None, **kwargs):
    defaults = dict(
        name="接口", code="api1", mode=HttpEndpoint.Mode.EXPOSE,
        script=script, method="GET", url="",
        auth_type=HttpEndpoint.AuthType.NONE, status="enabled",
        timeout=10, business=biz, environment=env,
        params_schema=[{"name": "host", "type": "string", "required": True}],
    )
    defaults.update(kwargs)
    return HttpEndpoint.objects.create(**defaults)


# ---------------------------------------------------------------------------
# API Key 哈希
# ---------------------------------------------------------------------------
class ApiKeyTests(TestCase):
    def test_hash_stored_not_plain(self):
        _, biz, env, _ = make_env()
        endpoint = HttpEndpoint.objects.create(
            name="k", code="k1", mode=HttpEndpoint.Mode.EXPOSE, business=biz
        )
        endpoint.set_api_key("secret-key-123")
        endpoint.save(update_fields=["auth_key_hash"])
        self.assertNotIn("secret-key-123", endpoint.auth_key_hash)
        self.assertTrue(endpoint.verify_api_key("secret-key-123"))
        self.assertFalse(endpoint.verify_api_key("wrong"))
        self.assertFalse(endpoint.verify_api_key(""))


# ---------------------------------------------------------------------------
# 健康统计
# ---------------------------------------------------------------------------
class HealthStatsTests(TestCase):
    def setUp(self):
        _, biz, env, _ = make_env()
        self.endpoint = make_endpoint(biz, env)

    def _add_calls(self, results):
        for success in results:
            EndpointCallLog.objects.create(
                endpoint=self.endpoint,
                mode=HttpEndpoint.Mode.MONITOR,
                method="GET",
                url="http://x",
                status_code=200 if success else 500,
                response_ms=100 if success else 500,
                success=success,
            )

    def test_all_success_healthy(self):
        self._add_calls([True, True, True])
        update_health_stats(self.endpoint)
        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.health_status, HttpEndpoint.HealthStatus.HEALTHY)
        self.assertEqual(self.endpoint.error_rate, 0)
        self.assertEqual(self.endpoint.call_count, 3)
        self.assertEqual(self.endpoint.avg_response_ms, 100)

    def test_high_error_rate_down(self):
        self._add_calls([False] * 4 + [True])
        update_health_stats(self.endpoint)
        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.health_status, HttpEndpoint.HealthStatus.DOWN)
        self.assertEqual(self.endpoint.error_rate, 0.8)

    def test_partial_failure_degraded(self):
        # 错误率 10% (0 < 0.1 < 0.2) → degraded
        self._add_calls([True] * 9 + [False])
        update_health_stats(self.endpoint)
        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.health_status, HttpEndpoint.HealthStatus.DEGRADED)
        self.assertEqual(self.endpoint.error_rate, 0.1)

    def test_no_calls_unknown(self):
        update_health_stats(self.endpoint)
        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.health_status, HttpEndpoint.HealthStatus.UNKNOWN)


# ---------------------------------------------------------------------------
# monitor 探测
# ---------------------------------------------------------------------------
class ProbeTests(TestCase):
    def setUp(self):
        _, biz, env, _ = make_env()
        self.endpoint = make_endpoint(
            biz, env, mode=HttpEndpoint.Mode.MONITOR, url="http://svc.local/health",
            method="GET",
        )

    def test_probe_success(self):
        with patch(
            "ops_platform.apps.endpoints.services.requests.request"
        ) as mock_req:
            mock_req.return_value.status_code = 200
            result = probe_endpoint(self.endpoint)
        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(self.endpoint.call_logs.count(), 1)
        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.health_status, HttpEndpoint.HealthStatus.HEALTHY)

    def test_probe_http_error(self):
        with patch(
            "ops_platform.apps.endpoints.services.requests.request"
        ) as mock_req:
            mock_req.return_value.status_code = 500
            result = probe_endpoint(self.endpoint)
        self.assertFalse(result["success"])
        self.assertIn("500", result["error_message"])

    def test_probe_connection_error(self):
        import requests as requests_lib

        with patch(
            "ops_platform.apps.endpoints.services.requests.request"
        ) as mock_req:
            mock_req.side_effect = requests_lib.ConnectionError("refused")
            result = probe_endpoint(self.endpoint)
        self.assertFalse(result["success"])
        self.assertIn("ConnectionError", result["error_message"])

    def test_monitor_task_only_enabled(self):
        with patch(
            "ops_platform.apps.endpoints.services.requests.request"
        ) as mock_req:
            mock_req.return_value.status_code = 200
            result = monitor_endpoints()
        self.assertEqual(result["checked"], 1)
        # 停用后不再巡检
        self.endpoint.status = "disabled"
        self.endpoint.save(update_fields=["status"])
        with patch(
            "ops_platform.apps.endpoints.services.requests.request"
        ) as mock_req:
            result = monitor_endpoints()
        self.assertEqual(result["checked"], 0)


# ---------------------------------------------------------------------------
# invoke 调用入口
# ---------------------------------------------------------------------------
class InvokeApiTests(APITestCase):
    def setUp(self):
        self.owner, self.biz, self.env, self.script = make_env()

    def _make(self, **kwargs):
        defaults = dict(script=self.script)
        defaults.update(kwargs)
        return make_endpoint(self.biz, self.env, **defaults)

    def _post(self, code, payload=None, headers=None):
        return self.client.post(
            f"/api/endpoints/invoke/{code}/",
            payload or {"params": {"host": "h1"}},
            format="json",
            headers=headers or {},
        )

    def test_invoke_api_key_success(self):
        endpoint = self._make(
            auth_type=HttpEndpoint.AuthType.API_KEY,
        )
        endpoint.set_api_key("the-key")
        endpoint.save(update_fields=["auth_key_hash"])
        with patch("ops_platform.apps.endpoints.views.execute_asset.delay") as mock_delay:
            resp = self._post("api1", headers={"X-API-Key": "the-key"})
            mock_delay.assert_called_once()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.data)
        self.assertIn("execution_id", resp.data)
        self.assertEqual(EndpointCallLog.objects.get().caller, "api_key:api1")

    def test_invoke_api_key_wrong(self):
        self._make(auth_type=HttpEndpoint.AuthType.API_KEY)
        resp = self._post("api1", headers={"X-API-Key": "wrong"})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invoke_requires_jwt_without_api_key(self):
        self._make()  # auth none
        resp = self._post("api1")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        # 登录后无权限 → 403
        user = User.objects.create_user("nobody", "n@test.local", "nobody-pass-123")
        self.client.force_authenticate(user)
        resp = self._post("api1")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_invoke_with_permission(self):
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        from ops_platform.apps.accounts.models import Role

        self._make()
        user = User.objects.create_user("caller", "c@test.local", "caller-pass-123")
        role = Role.objects.create(name="调用者", code="invoker")
        perm = Permission.objects.get(
            codename="execute_endpoint",
            content_type=ContentType.objects.get_for_model(HttpEndpoint),
        )
        role.permissions.add(perm)
        user.roles.add(role)
        self.client.force_authenticate(user)
        with patch("ops_platform.apps.endpoints.views.execute_asset.delay") as mock_delay:
            resp = self._post("api1")
            mock_delay.assert_called_once()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.data)

    def test_invoke_errors(self):
        self._make(status="disabled")
        self.assertEqual(self._post("api1").status_code, status.HTTP_400_BAD_REQUEST)
        self._make(code="mon", mode=HttpEndpoint.Mode.MONITOR, url="http://x", script=None)
        self.assertEqual(self._post("mon").status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._post("nope").status_code, status.HTTP_404_NOT_FOUND)

    def test_invoke_param_validation(self):
        self._make()
        user = User.objects.create_superuser("s", "s@test.local", "s-pass-123")
        self.client.force_authenticate(user)
        resp = self.client.post(
            "/api/endpoints/invoke/api1/", {"params": {}}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 真实执行:ENDPOINT 资产
# ---------------------------------------------------------------------------
class EndpointExecuteTests(TransactionTestCase):
    def test_execute_endpoint_updates_call_log(self):
        _, biz, env, script = make_env()
        endpoint = make_endpoint(biz, env, script)
        execution = Execution.objects.create(
            asset_type=Execution.AssetType.ENDPOINT,
            asset_id=endpoint.pk,
            trigger_type=Execution.TriggerType.API,
            request_id="req-endpoint-1",
            params={"host": "h1"},
            business=biz,
            environment=env,
        )
        EndpointCallLog.objects.create(
            endpoint=endpoint,
            mode=HttpEndpoint.Mode.EXPOSE,
            method="POST",
            url="/api/endpoints/invoke/api1/",
            request_id=execution.request_id,
            caller="tester",
        )
        result = execute_asset(execution.pk)
        self.assertEqual(result["status"], Execution.Status.SUCCESS)
        call = EndpointCallLog.objects.get(request_id=execution.request_id)
        self.assertTrue(call.success)
        self.assertIsNotNone(call.response_ms)
        endpoint.refresh_from_db()
        self.assertEqual(endpoint.health_status, HttpEndpoint.HealthStatus.HEALTHY)


# ---------------------------------------------------------------------------
# CRUD API
# ---------------------------------------------------------------------------
class EndpointApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@test.local", "admin-pass-123")
        self.client.force_authenticate(self.admin)
        _, self.biz, self.env, self.script = make_env()

    def _create(self, **kwargs):
        data = {
            "name": "同步接口",
            "code": "sync_api",
            "mode": "expose",
            "script": self.script.pk,
            "auth_type": "none",
            "business": self.biz.pk,
            "environment": self.env.pk,
        }
        data.update(kwargs)
        return self.client.post("/api/endpoints/", data, format="json")

    def test_create_expose(self):
        resp = self._create()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["health_status"], "unknown")

    def test_create_expose_requires_script(self):
        resp = self._create(script=None)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_monitor_requires_url(self):
        resp = self._create(mode="monitor", script=None)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_api_key_requires_auth_key(self):
        resp = self._create(auth_type="api_key")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        resp = self._create(auth_type="api_key", auth_key="my-secret")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        endpoint = HttpEndpoint.objects.get(pk=resp.data["id"])
        self.assertNotIn("my-secret", endpoint.auth_key_hash)
        self.assertTrue(endpoint.verify_api_key("my-secret"))
        # 读接口不回显 auth_key
        detail = self.client.get(f"/api/endpoints/{resp.data['id']}/")
        self.assertNotIn("auth_key", detail.data)

    def test_enable_disable(self):
        eid = self._create().data["id"]
        self.assertEqual(self.client.post(f"/api/endpoints/{eid}/enable/").data["status"], "enabled")
        self.assertEqual(self.client.post(f"/api/endpoints/{eid}/disable/").data["status"], "disabled")

    def test_list_respects_data_scope(self):
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        from ops_platform.apps.accounts.models import Role

        self._create()
        user = User.objects.create_user("nobody", "n@test.local", "nobody-pass-123")
        role = Role.objects.create(name="查看者", code="viewer")
        perm = Permission.objects.get(
            codename="view_endpoint",
            content_type=ContentType.objects.get_for_model(HttpEndpoint),
        )
        role.permissions.add(perm)
        user.roles.add(role)
        self.client.force_authenticate(user)
        resp = self.client.get("/api/endpoints/")
        self.assertEqual(resp.data["count"], 0)
        DataScope.objects.create(user=user, business=self.biz)
        resp = self.client.get("/api/endpoints/")
        self.assertEqual(resp.data["count"], 1)
