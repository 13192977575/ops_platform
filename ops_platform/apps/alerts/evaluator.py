"""告警评估器:执行结果 / 接口健康 → 规则匹配 → 发送 + 静默收敛。

触发时机(接线):
- execute_asset 执行结束后调用 evaluate_execution(覆盖 连续失败/超时);
- monitor 巡检探测后调用 evaluate_endpoint(覆盖 接口不可用/响应慢)。

静默收敛:同一规则最近一次"已发送"记录在 silent_minutes 内时,新触发记为
SILENCED(抑制)而不发送,防止告警风暴。
"""
from __future__ import annotations

from django.utils import timezone

from ops_platform.apps.executions.models import Execution

from . import notify
from .models import AlertRecord, AlertRule

_FAIL_STATUSES = (Execution.Status.FAILED, Execution.Status.TIMEOUT)


def evaluate_execution(execution) -> None:
    """执行结束后评估该资产上的启用规则(连续失败/超时)。"""
    rules = _rules_for(execution.asset_type, execution.asset_id)
    for rule in rules:
        message = _match_execution(rule, execution)
        if message:
            _trigger(rule, message, execution.asset_type, execution.asset_id)


def evaluate_endpoint(endpoint) -> None:
    """接口健康巡检后评估(不可用/响应慢)。"""
    rules = _rules_for(AlertRule.AssetType.ENDPOINT, endpoint.pk)
    for rule in rules:
        message = _match_endpoint(rule, endpoint)
        if message:
            _trigger(rule, message, AlertRule.AssetType.ENDPOINT, endpoint.pk)


def _rules_for(asset_type: str, asset_id: int):
    return AlertRule.objects.filter(
        enabled=True, asset_type=asset_type, asset_id=asset_id
    ).prefetch_related("channels")


def _match_execution(rule: AlertRule, execution) -> str | None:
    if rule.metric == AlertRule.Metric.TIMEOUT:
        if execution.status == Execution.Status.TIMEOUT:
            return (
                f"执行超时: {execution.asset_type}:{execution.asset_id}"
                f"(execution #{execution.pk})"
            )
        return None
    if rule.metric == AlertRule.Metric.CONSECUTIVE_FAILURES:
        if execution.status not in _FAIL_STATUSES:
            return None
        count = consecutive_failures(execution.asset_type, execution.asset_id)
        if count >= int(rule.threshold):
            return (
                f"连续失败 {count} 次(阈值 {int(rule.threshold)}): "
                f"{execution.asset_type}:{execution.asset_id}"
            )
        return None
    return None


def _match_endpoint(rule: AlertRule, endpoint) -> str | None:
    if rule.metric == AlertRule.Metric.ENDPOINT_UNAVAILABLE:
        if endpoint.health_status == "down":
            return (
                f"接口不可用: {endpoint.name}({endpoint.code}),"
                f"错误率 {endpoint.error_rate or 0:.0%}"
            )
        return None
    if rule.metric == AlertRule.Metric.ENDPOINT_SLOW:
        avg = endpoint.avg_response_ms
        if avg is not None and avg >= rule.threshold:
            return (
                f"接口响应慢: {endpoint.name}({endpoint.code}) "
                f"{avg:.0f}ms >= {rule.threshold:.0f}ms"
            )
        return None
    return None


def consecutive_failures(asset_type: str, asset_id: int, limit: int = 50) -> int:
    """统计资产最近连续失败(FAILED/TIMEOUT)次数,遇到成功即停止。"""
    statuses = list(
        Execution.objects.filter(asset_type=asset_type, asset_id=asset_id)
        .order_by("-id")[:limit]
        .values_list("status", flat=True)
    )
    count = 0
    for status in statuses:
        if status in _FAIL_STATUSES:
            count += 1
        else:
            break
    return count


def _trigger(rule: AlertRule, message: str, asset_type: str, asset_id: int):
    now = timezone.now()
    # 静默收敛:同规则最近"已发送"记录在窗口内 → 抑制
    recent = (
        AlertRecord.objects.filter(rule=rule, status=AlertRecord.Status.SENT)
        .order_by("-created_at")
        .first()
    )
    if recent is not None and (
        now - recent.created_at
    ).total_seconds() < rule.silent_minutes * 60:
        return AlertRecord.objects.create(
            rule=rule,
            asset_type=asset_type,
            asset_id=asset_id,
            metric=rule.metric,
            severity=rule.severity,
            message=message,
            status=AlertRecord.Status.SILENCED,
        )

    channels = list(rule.channels.filter(enabled=True))
    results: dict = {}
    for channel in channels:
        ok, error = notify.send(channel, message)
        results[channel.name] = {"success": ok, "error": error}

    if not results:
        status = AlertRecord.Status.FAILED
    else:
        status = (
            AlertRecord.Status.SENT
            if all(r["success"] for r in results.values())
            else AlertRecord.Status.FAILED
        )
    return AlertRecord.objects.create(
        rule=rule,
        asset_type=asset_type,
        asset_id=asset_id,
        metric=rule.metric,
        severity=rule.severity,
        message=message,
        status=status,
        channels=[c.name for c in channels],
        send_result=results,
    )
