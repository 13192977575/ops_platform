"""schedules 测试:cron 解析、PeriodicTask 信号同步、调度执行、重试、并发控制、API。"""
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from rest_framework import status
from rest_framework.test import APITestCase

from ops_platform.apps.accounts.models import Business, Environment, User
from ops_platform.apps.executions.models import Execution
from ops_platform.apps.executions.tasks import execute_asset
from ops_platform.apps.scripts.models import Script, ScriptVersion

from .cron import CronParseError, parse_cron
from .models import ScheduleTask
from .tasks import run_schedule


def make_script(code="print('ok')", **kwargs):
    owner = User.objects.create_user("owner", "owner@test.local", "owner-pass-123")
    biz = Business.objects.create(name="业务", code="biz")
    env = Environment.objects.create(name="生产", code="prod")
    script = Script.objects.create(
        name="测试脚本", code="t_script", owner=owner, business=biz, environment=env,
        timeout_seconds=10,
    )
    ScriptVersion.objects.create(
        script=script, version=1, code=code, is_current=True, created_by=owner
    )
    script.current_version = 1
    script.save(update_fields=["current_version"])
    return script


# ---------------------------------------------------------------------------
# cron 解析器
# ---------------------------------------------------------------------------
class CronParseTests(TestCase):
    def test_basic_fields(self):
        self.assertEqual(
            parse_cron("0 3 * * *"),
            {"minute": "0", "hour": "3", "day_of_month": "*",
             "month_of_year": "*", "day_of_week": "*"},
        )

    def test_step_range_list(self):
        result = parse_cron("*/5 1-3 1,15 * 1-5")
        self.assertEqual(result["minute"], "*/5")
        self.assertEqual(result["hour"], "1-3")
        self.assertEqual(result["day_of_month"], "1,15")
        self.assertEqual(result["day_of_week"], "1-5")

    def test_weekday_7_maps_to_0(self):
        self.assertEqual(parse_cron("0 0 * * 7")["day_of_week"], "0")
        self.assertEqual(parse_cron("0 0 * * 0,7")["day_of_week"], "0,0")

    def test_invalid_expressions(self):
        with self.assertRaises(CronParseError):
            parse_cron("0 3 * *")  # 4 段
        with self.assertRaises(CronParseError):
            parse_cron("60 3 * * *")  # 分钟越界
        with self.assertRaises(CronParseError):
            parse_cron("0 25 * * *")  # 小时越界
        with self.assertRaises(CronParseError):
            parse_cron("x 3 * * *")  # 非法 token
        with self.assertRaises(CronParseError):
            parse_cron("0 3 * * 8")  # 周越界


# ---------------------------------------------------------------------------
# PeriodicTask 信号同步
# ---------------------------------------------------------------------------
class SignalSyncTests(TestCase):
    def setUp(self):
        self.script = make_script()

    def _create_schedule(self, **kwargs):
        defaults = dict(
            name="每日同步",
            code="daily_sync",
            script=self.script,
            schedule_type=ScheduleTask.ScheduleType.CRON,
            cron_expr="0 2 * * *",
            enabled=True,
            business=self.script.business,
            environment=self.script.environment,
        )
        defaults.update(kwargs)
        return ScheduleTask.objects.create(**defaults)

    def test_create_cron_creates_periodic_task(self):
        schedule = self._create_schedule()
        pt = PeriodicTask.objects.get(schedule_task=schedule)
        self.assertEqual(pt.task, "schedules.run_schedule")
        self.assertEqual(pt.enabled, True)
        self.assertIsNotNone(pt.crontab)
        self.assertIsNone(pt.interval)

    def test_create_interval_creates_periodic_task(self):
        schedule = self._create_schedule(
            schedule_type=ScheduleTask.ScheduleType.INTERVAL,
            interval_seconds=300,
            cron_expr="",
        )
        pt = PeriodicTask.objects.get(schedule_task=schedule)
        self.assertIsNotNone(pt.interval)
        self.assertEqual(pt.interval.every, 300)

    def test_disable_and_enable_sync(self):
        schedule = self._create_schedule()
        schedule.enabled = False
        schedule.save(update_fields=["enabled"])
        pt = PeriodicTask.objects.get(schedule_task=schedule)
        self.assertFalse(pt.enabled)
        schedule.enabled = True
        schedule.save(update_fields=["enabled"])
        pt.refresh_from_db()
        self.assertTrue(pt.enabled)

    def test_cron_change_updates_crontab(self):
        schedule = self._create_schedule()
        pt = PeriodicTask.objects.get(schedule_task=schedule)
        old_crontab = pt.crontab
        schedule.cron_expr = "30 6 * * *"
        schedule.save(update_fields=["cron_expr"])
        pt.refresh_from_db()
        self.assertNotEqual(pt.crontab_id, old_crontab.pk)
        self.assertEqual(pt.crontab.hour, "6")

    def test_delete_removes_periodic_task(self):
        schedule = self._create_schedule()
        pt = PeriodicTask.objects.get(schedule_task=schedule)
        schedule.delete()
        self.assertFalse(PeriodicTask.objects.filter(pk=pt.pk).exists())


# ---------------------------------------------------------------------------
# 调度执行:run_schedule + execute_asset(真实子进程)
# ---------------------------------------------------------------------------
class ScheduleExecutionTests(TransactionTestCase):
    def _make_schedule(self, script, **kwargs):
        defaults = dict(
            name="调度任务",
            code="sched",
            script=script,
            schedule_type=ScheduleTask.ScheduleType.CRON,
            cron_expr="0 2 * * *",
            enabled=True,
            max_retries=0,
            retry_delay=0,
            concurrency_limit=1,
            business=script.business,
            environment=script.environment,
        )
        defaults.update(kwargs)
        return ScheduleTask.objects.create(**defaults)

    def test_run_schedule_creates_execution_and_dispatches(self):
        script = make_script(code="print('ok'); import time; time.sleep(0.05)")
        schedule = self._make_schedule(script)
        with patch("ops_platform.apps.schedules.tasks.execute_asset.delay") as mock_delay:
            result = run_schedule(schedule.pk)
        mock_delay.assert_called_once()
        execution = Execution.objects.get(pk=result["execution_id"])
        self.assertEqual(execution.asset_type, Execution.AssetType.SCHEDULE)
        self.assertEqual(execution.trigger_type, Execution.TriggerType.SCHEDULE)
        self.assertEqual(execution.asset_id, schedule.pk)

    def test_run_schedule_disabled_skipped(self):
        script = make_script()
        schedule = self._make_schedule(script, enabled=False)
        result = run_schedule(schedule.pk)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "disabled")

    def test_run_schedule_concurrency_limit_skipped(self):
        script = make_script()
        schedule = self._make_schedule(script, concurrency_limit=1)
        Execution.objects.create(
            asset_type=Execution.AssetType.SCHEDULE,
            asset_id=schedule.pk,
            trigger_type=Execution.TriggerType.SCHEDULE,
            status=Execution.Status.RUNNING,
            request_id="req-running",
            business=script.business,
        )
        result = run_schedule(schedule.pk)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "concurrency_limit")

    def test_execute_success_updates_stats(self):
        script = make_script(code="print('ok'); import time; time.sleep(0.05)")
        schedule = self._make_schedule(script)
        execution = Execution.objects.create(
            asset_type=Execution.AssetType.SCHEDULE,
            asset_id=schedule.pk,
            trigger_type=Execution.TriggerType.SCHEDULE,
            request_id="req-1",
            params={},
            business=script.business,
        )
        result = execute_asset(execution.pk)
        self.assertEqual(result["status"], Execution.Status.SUCCESS)
        schedule.refresh_from_db()
        self.assertEqual(schedule.consecutive_failures, 0)
        self.assertIsNotNone(schedule.last_run_at)

    def test_retry_until_success(self):
        # 脚本总是失败,max_retries=2:验证重试计数、最终状态与"第 N 次"日志
        script = make_script(code="import sys; sys.exit(1)")
        schedule = self._make_schedule(script, max_retries=2, retry_delay=0)
        execution = Execution.objects.create(
            asset_type=Execution.AssetType.SCHEDULE,
            asset_id=schedule.pk,
            trigger_type=Execution.TriggerType.SCHEDULE,
            request_id="req-retry",
            params={},
            business=script.business,
        )
        result = execute_asset(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(result["status"], Execution.Status.FAILED)
        self.assertEqual(execution.retry_count, 2)
        messages = list(execution.logs.values_list("message", flat=True))
        self.assertTrue(any("第 3 次" in m for m in messages), messages)
        schedule.refresh_from_db()
        self.assertEqual(schedule.consecutive_failures, 1)

    def test_consecutive_failures_increment_and_reset(self):
        script = make_script(code="import sys; sys.exit(1)")
        schedule = self._make_schedule(script, max_retries=0)
        for _ in range(2):
            execution = Execution.objects.create(
                asset_type=Execution.AssetType.SCHEDULE,
                asset_id=schedule.pk,
                trigger_type=Execution.TriggerType.SCHEDULE,
                request_id="req-x",
                params={},
                business=script.business,
            )
            execute_asset(execution.pk)
        schedule.refresh_from_db()
        self.assertEqual(schedule.consecutive_failures, 2)
        # 将脚本版本改为成功后,连续失败清零
        schedule.script.versions.filter(version=1).update(code="print('ok')")
        execution = Execution.objects.create(
            asset_type=Execution.AssetType.SCHEDULE,
            asset_id=schedule.pk,
            trigger_type=Execution.TriggerType.SCHEDULE,
            request_id="req-ok",
            params={},
            business=script.business,
        )
        execute_asset(execution.pk)
        schedule.refresh_from_db()
        self.assertEqual(schedule.consecutive_failures, 0)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class ScheduleApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@test.local", "admin-pass-123")
        self.client.force_authenticate(self.admin)
        self.script = make_script()

    def _create_schedule(self, **kwargs):
        data = {
            "name": "每日同步",
            "code": "daily_sync",
            "script": self.script.pk,
            "schedule_type": "cron",
            "cron_expr": "0 2 * * *",
            "enabled": True,
            "business": self.script.business_id,
            "environment": self.script.environment_id,
        }
        data.update(kwargs)
        return self.client.post("/api/schedules/", data, format="json")

    def test_create_schedule(self):
        resp = self._create_schedule()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertTrue(PeriodicTask.objects.filter(schedule_task=resp.data["id"]).exists())

    def test_invalid_cron_rejected(self):
        resp = self._create_schedule(cron_expr="not a cron")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_type_fields_exclusive(self):
        resp = self._create_schedule(
            schedule_type="interval", cron_expr="", interval_seconds=None
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_enable_disable_and_next_run(self):
        sid = self._create_schedule().data["id"]
        resp = self.client.post(f"/api/schedules/{sid}/disable/")
        self.assertFalse(resp.data["enabled"])
        pt = PeriodicTask.objects.get(schedule_task=sid)
        self.assertFalse(pt.enabled)
        resp = self.client.post(f"/api/schedules/{sid}/enable/")
        self.assertTrue(resp.data["enabled"])

    def test_run_now_dispatches(self):
        sid = self._create_schedule().data["id"]
        with patch("ops_platform.apps.schedules.views.run_schedule.delay") as mock_delay:
            resp = self.client.post(f"/api/schedules/{sid}/run_now/")
            mock_delay.assert_called_once_with(sid)
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

    def test_run_now_disabled_rejected(self):
        sid = self._create_schedule().data["id"]
        self.client.post(f"/api/schedules/{sid}/disable/")
        resp = self.client.post(f"/api/schedules/{sid}/run_now/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_contains_stats(self):
        sid = self._create_schedule().data["id"]
        resp = self.client.get("/api/schedules/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = next(x for x in resp.data["results"] if x["id"] == sid)
        self.assertIn("next_run_at", item)
        self.assertIn("recent_status", item)
        self.assertEqual(item["consecutive_failures"], 0)

    def test_schedule_respects_data_scope(self):
        self._create_schedule()
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        from ops_platform.apps.accounts.models import DataScope, Role

        user = User.objects.create_user("nobody", "n@test.local", "nobody-pass-123")
        role = Role.objects.create(name="查看者", code="viewer")
        perm = Permission.objects.get(
            codename="view_schedule",
            content_type=ContentType.objects.get_for_model(ScheduleTask),
        )
        role.permissions.add(perm)
        user.roles.add(role)
        self.client.force_authenticate(user)
        resp = self.client.get("/api/schedules/")
        self.assertEqual(resp.data["count"], 0)
        DataScope.objects.create(user=user, business=self.script.business)
        resp = self.client.get("/api/schedules/")
        self.assertEqual(resp.data["count"], 1)
