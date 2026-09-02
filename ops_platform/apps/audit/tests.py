"""audit 测试:仅追加保护、登录/资产操作埋点、查询 API。"""
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from ops_platform.apps.accounts.models import Business, Environment, Role, User
from ops_platform.apps.scripts.models import Script

from .models import AuditLog
from .services import write_audit


class AuditAppendOnlyTests(TestCase):
    def test_model_rejects_update_and_delete(self):
        log = write_audit(None, "test.action", "asset", 1, {"k": "v"}, "127.0.0.1")
        with self.assertRaises(NotImplementedError):
            log.detail = {"changed": True}
            log.save()
        with self.assertRaises(NotImplementedError):
            log.delete()
        # 记录仍存在且未被修改
        fresh = AuditLog.objects.get(pk=log.pk)
        self.assertEqual(fresh.detail, {"k": "v"})


class AuditLoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("dave", "d@test.local", "dave-pass-123")

    def test_login_success_audited(self):
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "dave", "password": "dave-pass-123"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(AuditLog.objects.filter(action="auth.login").exists())

    def test_login_failure_audited(self):
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "dave", "password": "wrong"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(AuditLog.objects.filter(action="auth.login_failed").exists())


class AuditInstrumentationTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@test.local", "admin-pass-123")
        self.client.force_authenticate(self.admin)
        self.biz = Business.objects.create(name="业务", code="biz")
        self.env = Environment.objects.create(name="生产", code="prod")

    def test_script_create_and_enable_audited(self):
        resp = self.client.post(
            "/api/scripts/",
            {
                "name": "脚本", "code": "sc1", "business": self.biz.pk,
                "environment": self.env.pk, "source_code": "print(1)",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(AuditLog.objects.filter(action="script.create").exists())
        self.client.post(f"/api/scripts/{resp.data['id']}/enable/")
        self.assertTrue(AuditLog.objects.filter(action="script.enable").exists())

    def test_script_execute_audited(self):
        created = self.client.post(
            "/api/scripts/",
            {
                "name": "脚本", "code": "sc2", "business": self.biz.pk,
                "environment": self.env.pk, "source_code": "print(1)",
            },
            format="json",
        ).data
        sid = created["id"]
        self.client.post(f"/api/scripts/{sid}/enable/")
        with patch("ops_platform.apps.scripts.views.execute_asset.delay"):
            self.client.post(
                f"/api/scripts/{sid}/execute/", {"params": {}}, format="json"
            )
        self.assertTrue(
            AuditLog.objects.filter(action="script.execute", target_id=str(sid)).exists()
        )

    def test_endpoint_invoke_audited(self):
        owner = User.objects.create_user("owner", "o@test.local", "o-pass-123")
        script = Script.objects.create(
            name="s", code="s1", owner=owner, business=self.biz, environment=self.env
        )
        from ops_platform.apps.scripts.models import ScriptVersion

        ScriptVersion.objects.create(script=script, version=1, code="print(1)", is_current=True)
        script.current_version = 1
        script.save(update_fields=["current_version"])
        endpoint = self.client.post(
            "/api/endpoints/",
            {
                "name": "接口", "code": "ep1", "mode": "expose",
                "script": script.pk, "auth_type": "api_key", "auth_key": "k-123",
                "status": "enabled",
                "business": self.biz.pk, "environment": self.env.pk,
            },
            format="json",
        ).data
        with patch("ops_platform.apps.endpoints.views.execute_asset.delay"):
            resp = self.client.post(
                "/api/endpoints/invoke/ep1/",
                {"params": {"host": "h"}},
                format="json",
                headers={"X-API-Key": "k-123"},
            )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(
            AuditLog.objects.filter(
                action="endpoint.invoke", target_id=str(endpoint["id"])
            ).exists()
        )


class AuditQueryTests(APITestCase):
    def test_query_requires_permission_and_filters(self):
        user = User.objects.create_user("auditor", "a2@test.local", "a-pass-123")
        role = Role.objects.create(name="审计员", code="auditor")
        perm = Permission.objects.get(
            codename="view_auditlog",
            content_type=ContentType.objects.get_for_model(AuditLog),
        )
        role.permissions.add(perm)
        user.roles.add(role)
        write_audit(user, "script.create", "script", 1, ip="10.0.0.1")
        write_audit(user, "schedule.disable", "schedule", 2, ip="10.0.0.2")
        self.client.force_authenticate(user)
        resp = self.client.get("/api/audit-logs/?action=script.create")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["actor"], user.username)

    def test_denied_without_permission(self):
        user = User.objects.create_user("nobody", "n2@test.local", "n-pass-123")
        self.client.force_authenticate(user)
        resp = self.client.get("/api/audit-logs/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
