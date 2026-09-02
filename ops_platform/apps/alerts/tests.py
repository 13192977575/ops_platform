"""alerts 测试:凭据加密、渠道发送、评估匹配、静默收敛、接线、API。"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from ops_platform.apps.accounts.models import Business, DataScope, Environment, Role, User
from ops_platform.apps.endpoints.models import HttpEndpoint
from ops_platform.apps.executions.models import Execution
from ops_platform.apps.executions.tasks import execute_asset
from ops_platform.apps.scripts.models import Script, ScriptVersion

from .crypto import decrypt_config, encrypt_config
from .evaluator import evaluate_endpoint, evaluate_execution
from .models import AlertChannel, AlertRecord, AlertRule
from .notify import send


def make_script():
    owner = User.objects.create_user("owner", "owner@test.local", "owner-pass-123")
    biz = Business.objects.create(name="业务", code="biz")
    env = Environment.objects.create(name="生产", code="prod")
    script = Script.objects.create(
        name="测试脚本", code="t_script", owner=owner, business=biz, environment=env,
        timeout_seconds=10,
    )
    ScriptVersion.objects.create(
        script=script, version=1, code="print('ok')", is_current=True, created_by=owner
    )
    script.current_version = 1
    script.save(update_fields=["current_version"])
    return owner, biz, env, script


def make_channel(name="企微", **kwargs):
    defaults = dict(
        name=name, type=AlertChannel.ChannelType.WECOM,
        config={"webhook_url": "https://qyapi.weixin.qq.com/hook", "mention": "all"},
    )
    defaults.update(kwargs)
    channel = AlertChannel(**defaults)
    channel.set_config(channel.config)
    channel.save()
    return channel


# ---------------------------------------------------------------------------
# 凭据加密
# ---------------------------------------------------------------------------
class CryptoTests(TestCase):
    def test_sensitive_keys_encrypted(self):
        plain = {"webhook_url": "https://x/hook", "mention": "all", "secret": "s3"}
        stored = encrypt_config(plain)
        self.assertTrue(stored["webhook_url"].startswith("enc:"))
        self.assertTrue(stored["secret"].startswith("enc:"))
        self.assertEqual(stored["mention"], "all")
        self.assertNotIn("https://x/hook", stored["webhook_url"])
        self.assertEqual(decrypt_config(stored), plain)

    def test_channel_set_and_get_config(self):
        channel = make_channel()
        self.assertTrue(channel.config["webhook_url"].startswith("enc:"))
        self.assertEqual(channel.get_config()["webhook_url"], "https://qyapi.weixin.qq.com/hook")


# ---------------------------------------------------------------------------
# 渠道发送
# ---------------------------------------------------------------------------
class NotifyTests(TestCase):
    def test_wecom_sends_json(self):
        channel = make_channel()
        with patch("ops_platform.apps.alerts.notify.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            ok, err = send(channel, "测试告警")
        self.assertTrue(ok)
        self.assertEqual(err, "")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["msgtype"], "text")
        self.assertEqual(payload["text"]["content"], "测试告警")

    def test_webhook_http_error(self):
        channel = make_channel(type=AlertChannel.ChannelType.WEBHOOK, config={"url": "https://x/hook"})
        with patch("ops_platform.apps.alerts.notify.requests.post") as mock_post:
            mock_post.return_value.status_code = 500
            ok, err = send(channel, "x")
        self.assertFalse(ok)
        self.assertIn("500", err)

    def test_missing_url(self):
        channel = make_channel(config={"mention": "all"})
        ok, err = send(channel, "x")
        self.assertFalse(ok)
        self.assertIn("webhook url", err)

    def test_email_sends(self):
        channel = make_channel(type=AlertChannel.ChannelType.EMAIL, config={"to": "ops@example.com"})
        with patch("django.core.mail.send_mail") as mock_mail:
            ok, err = send(channel, "邮件告警", title="标题")
        self.assertTrue(ok)
        mock_mail.assert_called_once()
        self.assertEqual(mock_mail.call_args.kwargs["recipient_list"], ["ops@example.com"])


# ---------------------------------------------------------------------------
# 评估器
# ---------------------------------------------------------------------------
class EvaluatorTests(TestCase):
    def setUp(self):
        _, self.biz, self.env, self.script = make_script()
        self.channel = make_channel()
        self.execution = Execution.objects.create(
            asset_type=Execution.AssetType.SCRIPT, asset_id=self.script.pk,
            trigger_type="manual", request_id="req-a", status=Execution.Status.FAILED,
            business=self.biz, environment=self.env,
        )

    def _rule(self, metric, threshold=1, **kwargs):
        defaults = dict(
            name="规则", asset_type=AlertRule.AssetType.SCRIPT,
            asset_id=self.script.pk, metric=metric, threshold=threshold,
            severity=AlertRule.Severity.WARNING, business=self.biz,
        )
        defaults.update(kwargs)
        rule = AlertRule.objects.create(**defaults)
        rule.channels.add(self.channel)
        return rule

    def test_timeout_rule_triggers(self):
        self._rule(AlertRule.Metric.TIMEOUT)
        self.execution.status = Execution.Status.TIMEOUT
        with patch("ops_platform.apps.alerts.notify.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            evaluate_execution(self.execution)
        record = AlertRecord.objects.get(metric=AlertRule.Metric.TIMEOUT)
        self.assertEqual(record.status, AlertRecord.Status.SENT)
        self.assertIn("超时", record.message)

    def test_consecutive_failures_threshold(self):
        self._rule(AlertRule.Metric.CONSECUTIVE_FAILURES, threshold=2)
        Execution.objects.create(
            asset_type=Execution.AssetType.SCRIPT, asset_id=self.script.pk,
            trigger_type="manual", request_id="req-b", status=Execution.Status.FAILED,
            business=self.biz,
        )
        with patch("ops_platform.apps.alerts.notify.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            evaluate_execution(self.execution)
        record = AlertRecord.objects.get(metric=AlertRule.Metric.CONSECUTIVE_FAILURES)
        self.assertIn("连续失败 2 次", record.message)

    def test_threshold_not_met_no_trigger(self):
        self._rule(AlertRule.Metric.CONSECUTIVE_FAILURES, threshold=3)
        evaluate_execution(self.execution)
        self.assertFalse(AlertRecord.objects.exists())

    def test_silent_window_suppresses(self):
        rule = self._rule(AlertRule.Metric.TIMEOUT, silent_minutes=30)
        self.execution.status = Execution.Status.TIMEOUT
        with patch("ops_platform.apps.alerts.notify.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            evaluate_execution(self.execution)
        # 立即再次触发:窗口内 → 抑制
        evaluate_execution(self.execution)
        records = AlertRecord.objects.filter(rule=rule).order_by("created_at")
        self.assertEqual(records[0].status, AlertRecord.Status.SENT)
        self.assertEqual(records[1].status, AlertRecord.Status.SILENCED)
        # 超时窗口后不再抑制
        AlertRecord.objects.filter(pk=records[0].pk).update(
            created_at=timezone.now() - timedelta(hours=1)
        )
        with patch("ops_platform.apps.alerts.notify.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            evaluate_execution(self.execution)
        latest = AlertRecord.objects.filter(rule=rule).latest("created_at")
        self.assertEqual(latest.status, AlertRecord.Status.SENT)

    def test_endpoint_unavailable_triggers(self):
        endpoint = HttpEndpoint.objects.create(
            name="接口", code="ep", mode=HttpEndpoint.Mode.MONITOR,
            url="http://x", business=self.biz, environment=self.env,
            health_status=HttpEndpoint.HealthStatus.DOWN, error_rate=0.5,
        )
        rule = AlertRule.objects.create(
            name="接口不可用", asset_type=AlertRule.AssetType.ENDPOINT,
            asset_id=endpoint.pk, metric=AlertRule.Metric.ENDPOINT_UNAVAILABLE,
            severity=AlertRule.Severity.CRITICAL, business=self.biz,
        )
        rule.channels.add(self.channel)
        with patch("ops_platform.apps.alerts.notify.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            evaluate_endpoint(endpoint)
        record = AlertRecord.objects.get(metric=AlertRule.Metric.ENDPOINT_UNAVAILABLE)
        self.assertEqual(record.severity, AlertRule.Severity.CRITICAL)
        self.assertIn("接口不可用", record.message)

    def test_endpoint_slow_triggers(self):
        endpoint = HttpEndpoint.objects.create(
            name="接口", code="ep2", mode=HttpEndpoint.Mode.MONITOR,
            url="http://x", business=self.biz, environment=self.env,
            health_status=HttpEndpoint.HealthStatus.HEALTHY, avg_response_ms=800,
        )
        rule = AlertRule.objects.create(
            name="响应慢", asset_type=AlertRule.AssetType.ENDPOINT,
            asset_id=endpoint.pk, metric=AlertRule.Metric.ENDPOINT_SLOW,
            threshold=500, business=self.biz,
        )
        rule.channels.add(self.channel)
        with patch("ops_platform.apps.alerts.notify.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            evaluate_endpoint(endpoint)
        self.assertTrue(AlertRecord.objects.filter(metric=AlertRule.Metric.ENDPOINT_SLOW).exists())


# ---------------------------------------------------------------------------
# 接线:真实执行失败触发告警
# ---------------------------------------------------------------------------
class WiringTests(TransactionTestCase):
    def test_failed_execution_triggers_alert(self):
        owner, biz, env, script = make_script()
        # 脚本改为失败,创建连续失败规则(阈值 1)
        script.versions.filter(version=1).update(code="import sys; sys.exit(1)")
        channel = make_channel(name="企微接线")
        rule = AlertRule.objects.create(
            name="连续失败", asset_type=AlertRule.AssetType.SCRIPT,
            asset_id=script.pk, metric=AlertRule.Metric.CONSECUTIVE_FAILURES,
            threshold=1, business=biz,
        )
        rule.channels.add(channel)
        execution = Execution.objects.create(
            asset_type=Execution.AssetType.SCRIPT, asset_id=script.pk,
            trigger_type="manual", request_id="req-w", business=biz, environment=env,
        )
        with patch("ops_platform.apps.alerts.notify.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            execute_asset(execution.pk)
        record = AlertRecord.objects.get(rule=rule)
        self.assertEqual(record.status, AlertRecord.Status.SENT)
        self.assertIn("连续失败 1 次", record.message)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class AlertApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@test.local", "admin-pass-123")
        self.client.force_authenticate(self.admin)
        _, self.biz, self.env, self.script = make_script()

    def test_channel_create_and_masked_read(self):
        resp = self.client.post(
            "/api/alert-channels/",
            {"name": "钉钉", "type": "dingtalk", "config": {"webhook_url": "https://ding/hook"}},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["config"]["webhook_url"], "***")
        # 加密键已落库
        channel = AlertChannel.objects.get(pk=resp.data["id"])
        self.assertTrue(channel.config["webhook_url"].startswith("enc:"))

    def test_rule_create_validates_asset(self):
        resp = self.client.post(
            "/api/alert-rules/",
            {
                "name": "超时告警", "asset_type": "script", "asset_id": self.script.pk,
                "metric": "timeout", "business": self.biz.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        # 资产不存在 → 400
        resp = self.client.post(
            "/api/alert-rules/",
            {
                "name": "超时告警", "asset_type": "script", "asset_id": 999999,
                "metric": "timeout", "business": self.biz.pk,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rule_enable_disable(self):
        rid = self.client.post(
            "/api/alert-rules/",
            {
                "name": "规则", "asset_type": "script", "asset_id": self.script.pk,
                "metric": "timeout", "business": self.biz.pk,
            },
            format="json",
        ).data["id"]
        self.client.post(f"/api/alert-rules/{rid}/disable/")
        self.assertFalse(AlertRule.objects.get(pk=rid).enabled)
        self.client.post(f"/api/alert-rules/{rid}/enable/")
        self.assertTrue(AlertRule.objects.get(pk=rid).enabled)

    def test_record_ack(self):
        record = AlertRecord.objects.create(
            asset_type="script", asset_id=1, metric="timeout",
            severity="warning", message="x", status=AlertRecord.Status.SENT,
        )
        resp = self.client.post(f"/api/alert-records/{record.pk}/ack/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "acked")
        self.assertEqual(resp.data["acked_by"], self.admin.username)

    def test_permission_and_data_scope(self):
        user = User.objects.create_user("nobody", "n@test.local", "nobody-pass-123")
        self.client.force_authenticate(user)
        self.assertEqual(
            self.client.get("/api/alert-channels/").status_code, status.HTTP_403_FORBIDDEN
        )
        role = Role.objects.create(name="查看者", code="viewer")
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        perm = Permission.objects.get(
            codename="view_alert",
            content_type=ContentType.objects.get_for_model(AlertRule),
        )
        role.permissions.add(perm)
        user.roles.add(role)
        # 无数据范围 → 规则列表为空
        resp = self.client.get("/api/alert-rules/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 0)
        DataScope.objects.create(user=user, business=self.biz)
        # 用管理员创建规则,再切回普通用户验证数据范围
        self.client.force_authenticate(self.admin)
        self.client.post(
            "/api/alert-rules/",
            {
                "name": "规则", "asset_type": "script", "asset_id": self.script.pk,
                "metric": "timeout", "business": self.biz.pk,
            },
            format="json",
        )
        self.client.force_authenticate(user)
        resp = self.client.get("/api/alert-rules/")
        self.assertEqual(resp.data["count"], 1)
