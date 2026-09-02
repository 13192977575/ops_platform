"""审计服务:统一写入入口与动作常量。"""
from __future__ import annotations

from .models import AuditLog

# 动作常量(action 格式:<域>.<动作>)
ACTION_LOGIN = "auth.login"
ACTION_LOGIN_FAILED = "auth.login_failed"
ACTION_SCRIPT_CREATE = "script.create"
ACTION_SCRIPT_UPDATE = "script.update"
ACTION_SCRIPT_DELETE = "script.delete"
ACTION_SCRIPT_ENABLE = "script.enable"
ACTION_SCRIPT_DISABLE = "script.disable"
ACTION_SCRIPT_VERSION_CREATE = "script.version_create"
ACTION_SCRIPT_ROLLBACK = "script.version_rollback"
ACTION_SCRIPT_EXECUTE = "script.execute"
ACTION_SCHEDULE_CREATE = "schedule.create"
ACTION_SCHEDULE_UPDATE = "schedule.update"
ACTION_SCHEDULE_DELETE = "schedule.delete"
ACTION_SCHEDULE_ENABLE = "schedule.enable"
ACTION_SCHEDULE_DISABLE = "schedule.disable"
ACTION_SCHEDULE_RUN_NOW = "schedule.run_now"
ACTION_ENDPOINT_CREATE = "endpoint.create"
ACTION_ENDPOINT_UPDATE = "endpoint.update"
ACTION_ENDPOINT_DELETE = "endpoint.delete"
ACTION_ENDPOINT_ENABLE = "endpoint.enable"
ACTION_ENDPOINT_DISABLE = "endpoint.disable"
ACTION_ENDPOINT_INVOKE = "endpoint.invoke"


def request_ip(request) -> str:
    """从请求提取客户端 IP(支持 X-Forwarded-For)。"""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def write_audit(
    user,
    action: str,
    target_type: str = "",
    target_id=None,
    detail: dict | None = None,
    ip: str = "",
) -> AuditLog:
    """写入一条审计日志。user 可为 None(如登录失败、API Key 调用)。"""
    return AuditLog.objects.create(
        actor=user if user is not None and getattr(user, "is_authenticated", False) else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else "",
        detail=detail or {},
        ip=ip,
    )
