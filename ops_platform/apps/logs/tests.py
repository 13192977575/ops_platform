"""logs 测试:检索 API(过滤/搜索/时间/权限/数据范围)与保留清理。"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from ops_platform.apps.accounts.models import Business, DataScope, Environment, Role, User
from ops_platform.apps.executions.models import Execution

from .models import LogEntry
from .tasks import clean_old_logs


def make_execution(biz, env):
    return Execution.objects.create(
        asset_type="script", asset_id=1, trigger_type="manual",
        request_id="req-log", business=biz, environment=env,
    )


def make_log(execution, message, level="INFO", user="ops"):
    return LogEntry.objects.create(
        execution=execution, request_id=execution.request_id,
        user=user, level=level, message=message,
    )


class LogApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@test.local", "admin-pass-123")
        self.client.force_authenticate(self.admin)
        self.biz = Business.objects.create(name="业务", code="biz")
        self.env = Environment.objects.create(name="生产", code="prod")
        self.execution = make_execution(self.biz, self.env)
        make_log(self.execution, "连接成功 host=db1", level="INFO")
        make_log(self.execution, "处理失败 timeout", level="ERROR", user="alice")

    def test_list_and_filter_level(self):
        resp = self.client.get("/api/logs/?level=ERROR")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["message"], "处理失败 timeout")

    def test_filter_by_execution_and_user(self):
        resp = self.client.get(f"/api/logs/?execution={self.execution.pk}&user=alice")
        self.assertEqual(resp.data["count"], 1)

    def test_search_keyword(self):
        resp = self.client.get("/api/logs/?search=timeout")
        self.assertEqual(resp.data["count"], 1)

    def test_time_range(self):
        # 把最早一条日志改为未来时间,验证 created_after 过滤
        future = timezone.now() + timedelta(hours=1)
        LogEntry.objects.filter(pk=self.execution.logs.first().pk).update(created_at=future)
        # 用 data 参数传递(isoformat 含 + 号,URL 字符串拼接会被解析为空格)
        resp = self.client.get("/api/logs/", {"created_after": timezone.now().isoformat()})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)

    def test_requires_view_log_permission(self):
        user = User.objects.create_user("nobody", "n@test.local", "nobody-pass-123")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get("/api/logs/").status_code, status.HTTP_403_FORBIDDEN)
        role = Role.objects.create(name="查看者", code="viewer")
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        perm = Permission.objects.get(
            codename="view_log",
            content_type=ContentType.objects.get_for_model(LogEntry),
        )
        role.permissions.add(perm)
        user.roles.add(role)
        DataScope.objects.create(user=user, business=self.biz)
        resp = self.client.get("/api/logs/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 2)

    def test_data_scope_filters_logs(self):
        other_biz = Business.objects.create(name="其他", code="other")
        other_env = Environment.objects.create(name="测试", code="test")
        other_exec = make_execution(other_biz, other_env)
        make_log(other_exec, "其他业务的日志")
        user = User.objects.create_user("scoped", "s@test.local", "s-pass-123")
        role = Role.objects.create(name="查看者", code="viewer2")
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        perm = Permission.objects.get(
            codename="view_log",
            content_type=ContentType.objects.get_for_model(LogEntry),
        )
        role.permissions.add(perm)
        user.roles.add(role)
        DataScope.objects.create(user=user, business=self.biz)
        self.client.force_authenticate(user)
        resp = self.client.get("/api/logs/")
        self.assertEqual(resp.data["count"], 2)


class CleanLogsTests(TestCase):
    def test_clean_old_logs_deletes_expired_only(self):
        biz = Business.objects.create(name="业务", code="biz")
        env = Environment.objects.create(name="生产", code="prod")
        execution = make_execution(biz, env)
        make_log(execution, "旧的日志")
        make_log(execution, "新的日志")
        old_pk = execution.logs.first().pk
        LogEntry.objects.filter(pk=old_pk).update(
            created_at=timezone.now() - timedelta(days=100)
        )
        result = clean_old_logs(days=90)
        self.assertEqual(result["deleted"], 1)
        self.assertFalse(LogEntry.objects.filter(pk=old_pk).exists())
        self.assertEqual(execution.logs.count(), 1)
