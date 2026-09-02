"""公共视图:健康探活接口(部署/负载均衡探活用,无需认证)与平台仪表盘。"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone


def health(request):
    return JsonResponse(
        {
            "status": "ok",
            "service": "ops_platform",
            "time": timezone.now().isoformat(),
        }
    )


@login_required(login_url="/admin/login/")
def dashboard(request):
    """平台概览:资产/执行统计 + 最近执行(SimpleUI 首页)。"""
    from ops_platform.apps.alerts.models import AlertRecord
    from ops_platform.apps.endpoints.models import HttpEndpoint
    from ops_platform.apps.executions.models import Execution
    from ops_platform.apps.schedules.models import ScheduleTask
    from ops_platform.apps.scripts.models import Script

    total = Execution.objects.count()
    success = Execution.objects.filter(status="success").count()
    today = timezone.localdate()
    recent = list(
        Execution.objects.select_related("trigger_user")
        .order_by("-created_at")[:10]
        .values(
            "id",
            "asset_type",
            "asset_id",
            "status",
            "duration_ms",
            "trigger_user__username",
            "created_at",
        )
    )
    stats = {
        "scripts": Script.objects.count(),
        "schedules": ScheduleTask.objects.count(),
        "endpoints": HttpEndpoint.objects.count(),
        "executions": total,
        "success_rate": round(success / total * 100, 1) if total else 0,
        "today_executions": Execution.objects.filter(created_at__date=today).count(),
        "open_alerts": AlertRecord.objects.exclude(status="acked").count(),
    }
    return render(request, "common/dashboard.html", {"stats": stats, "recent": recent})
