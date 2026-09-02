"""日志写入服务:统一入口,所有执行日志经此入库(写入前自动敏感过滤)。"""
from __future__ import annotations

from .filter import filter_sensitive
from .models import LogEntry


def add_log(
    execution,
    message: str,
    level: str = "INFO",
    extra: dict | None = None,
    node: str | None = None,
    user: str | None = None,
) -> LogEntry:
    """写入一条执行日志。execution 为 Execution 实例或仅含 pk 的对象。"""
    safe_message, safe_extra = filter_sensitive(message, extra)
    trigger_user = getattr(execution, "trigger_user", None)
    username = user
    if username is None:
        username = getattr(trigger_user, "username", "") if trigger_user else ""
    return LogEntry.objects.create(
        execution_id=execution.pk,
        request_id=getattr(execution, "request_id", "") or "",
        user=username or "",
        level=str(level).upper(),
        node=node or getattr(execution, "node", "") or "",
        message=safe_message,
        extra=safe_extra,
    )


def log_stdout_line(execution, line: str, node: str = "") -> None:
    """处理一条原始输出行:优先解析统一 JSON 日志,否则按普通日志入库。"""
    line = line.rstrip("\r\n")
    if not line.strip():
        return
    import json

    try:
        record = json.loads(line)
        if isinstance(record, dict) and "message" in record:
            add_log(
                execution,
                record.get("message", ""),
                level=record.get("level", "INFO"),
                extra=record.get("extra") or {},
                node=record.get("node") or node,
            )
            return
    except (ValueError, TypeError):
        pass
    add_log(execution, line, level="INFO", node=node)
