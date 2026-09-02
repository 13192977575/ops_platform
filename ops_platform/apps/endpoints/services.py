"""接口监控与健康统计服务。

健康状态规则(滚动窗口 STATS_WINDOW 次调用):
- 错误率 0 → healthy;0 < 错误率 < 20% → degraded;>= 20% → down;
- 窗口无数据 → unknown。
"""
from __future__ import annotations

import time

import requests
from django.utils import timezone

from .models import EndpointCallLog, HttpEndpoint

# 健康统计窗口:最近 N 次调用
STATS_WINDOW = 50
# 错误率阈值:>= 该值视为不可用(down)
ERROR_RATE_DOWN = 0.2


def probe_endpoint(endpoint: HttpEndpoint) -> dict:
    """探测单个 monitor 接口:发起请求、记录调用日志、滚动更新健康统计。"""
    start = time.monotonic()
    success = False
    status_code = None
    error_message = ""
    try:
        resp = requests.request(endpoint.method, endpoint.url, timeout=endpoint.timeout)
        status_code = resp.status_code
        success = status_code < 400
        if not success:
            error_message = f"HTTP {status_code}"
    except requests.RequestException as exc:
        error_message = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # 兜底(如 URL 非法)
        error_message = f"{type(exc).__name__}: {exc}"

    response_ms = int((time.monotonic() - start) * 1000)
    EndpointCallLog.objects.create(
        endpoint=endpoint,
        mode=HttpEndpoint.Mode.MONITOR,
        method=endpoint.method,
        url=endpoint.url,
        status_code=status_code,
        response_ms=response_ms,
        success=success,
        error_message=error_message,
    )
    update_health_stats(endpoint)
    return {
        "success": success,
        "status_code": status_code,
        "response_ms": response_ms,
        "error_message": error_message,
    }


def update_health_stats(endpoint: HttpEndpoint) -> None:
    """按最近 STATS_WINDOW 次调用滚动更新接口健康统计。"""
    logs = list(
        endpoint.call_logs.order_by("-id")[:STATS_WINDOW].values("success", "response_ms")
    )
    total = len(logs)
    if total == 0:
        fields = {
            "health_status": HttpEndpoint.HealthStatus.UNKNOWN,
            "error_rate": None,
            "avg_response_ms": None,
            "call_count": 0,
        }
    else:
        failed = sum(1 for log in logs if not log["success"])
        error_rate = failed / total
        responses = [log["response_ms"] for log in logs if log["response_ms"] is not None]
        avg_ms = round(sum(responses) / len(responses), 1) if responses else None
        if error_rate == 0:
            health = HttpEndpoint.HealthStatus.HEALTHY
        elif error_rate < ERROR_RATE_DOWN:
            health = HttpEndpoint.HealthStatus.DEGRADED
        else:
            health = HttpEndpoint.HealthStatus.DOWN
        fields = {
            "health_status": health,
            "error_rate": round(error_rate, 4),
            "avg_response_ms": avg_ms,
            "call_count": total,
        }
    fields["last_check_at"] = timezone.now()
    HttpEndpoint.objects.filter(pk=endpoint.pk).update(**fields)
