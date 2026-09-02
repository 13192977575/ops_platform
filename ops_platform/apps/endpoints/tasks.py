"""接口监控巡检任务:由 PeriodicTask(monitor-endpoints)周期触发。"""
from __future__ import annotations

from celery import shared_task

from .models import HttpEndpoint
from .services import probe_endpoint


@shared_task(name="endpoints.monitor_endpoints")
def monitor_endpoints() -> dict:
    """巡检所有启用的 monitor 接口,逐个体检并滚动更新健康统计。"""
    endpoints = HttpEndpoint.objects.filter(
        mode=HttpEndpoint.Mode.MONITOR, status="enabled"
    )
    results = []
    for endpoint in endpoints:
        result = probe_endpoint(endpoint)
        result["endpoint_id"] = endpoint.pk
        results.append(result)
        # 告警评估(接口不可用/响应慢);评估异常不影响巡检结果
        try:
            from ops_platform.apps.alerts.evaluator import evaluate_endpoint

            evaluate_endpoint(endpoint)
        except Exception:
            pass
    return {"checked": len(results), "results": results}
