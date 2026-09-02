"""Celery 执行任务:Web 仅投递,Worker 异步执行(核心链路)。

资产类型:
- script:直接执行脚本(不重试);
- schedule:定时任务,执行其绑定的脚本,支持失败重试(状态经 retrying)与统计回写。

流程: pending → running → success|failed|timeout(重试时经 retrying)
- 幂等:仅 pending 状态才消费,防止重复投递重复执行;
- 执行器:按 runner 从注册表选择,超时/资源限制由执行器负责;
- 日志:执行器流式写入 LogEntry;
- 异常兜底:任何未捕获异常统一置 failed。
"""
from __future__ import annotations

import socket
import time

from celery import shared_task
from django.utils import timezone

from ops_platform.apps.executors.registry import ExecutorRegistry
from ops_platform.apps.logs.services import add_log
from ops_platform.apps.scripts.models import Script

from .models import Execution

_RUNNING_FIELDS = ("status", "started_at", "node", "worker_id", "updated_at")
_FINAL_FIELDS = (
    "status",
    "result_code",
    "error_message",
    "finished_at",
    "duration_ms",
    "updated_at",
)


@shared_task(bind=True, name="executions.execute_asset")
def execute_asset(self, execution_id: int) -> dict:
    execution = Execution.objects.select_related("trigger_user").get(pk=execution_id)

    # 幂等保护:已被消费或已结束的任务直接跳过
    if execution.status != Execution.Status.PENDING:
        return {
            "execution_id": execution_id,
            "status": execution.status,
            "skipped": True,
        }

    try:
        info = _resolve_asset(execution)
    except Script.DoesNotExist:
        # 区分"脚本不存在"与"脚本存在但当前版本未设置",便于排查
        script = (
            Script.objects.filter(pk=execution.asset_id)
            .only("code", "current_version")
            .first()
        )
        if script is not None:
            execution.status = Execution.Status.FAILED
            execution.error_message = (
                f"脚本 {script.code} 当前版本({script.current_version})不存在,"
                "请创建脚本版本并设置 current_version"
            )
        else:
            execution.status = Execution.Status.FAILED
            execution.error_message = f"脚本不存在(asset_id={execution.asset_id})"
        execution.finished_at = timezone.now()
        execution.save(update_fields=_FINAL_FIELDS)
        add_log(execution, execution.error_message, level="ERROR")
        return {"execution_id": execution_id, "status": execution.status}
    except Exception as exc:  # 资产解析失败(如版本缺失)视为失败
        execution.status = Execution.Status.FAILED
        execution.error_message = f"{type(exc).__name__}: {exc}"
        execution.finished_at = timezone.now()
        execution.save(update_fields=_FINAL_FIELDS)
        add_log(execution, execution.error_message, level="ERROR")
        return {"execution_id": execution_id, "status": execution.status}

    max_retries = info["max_retries"]
    retry_delay = info["retry_delay"]
    attempt = 0
    while True:
        attempt += 1
        execution.status = Execution.Status.RUNNING
        execution.started_at = timezone.now()
        execution.node = socket.gethostname()
        execution.worker_id = self.request.id or ""
        execution.save(update_fields=_RUNNING_FIELDS)
        add_log(execution, f"开始执行(第 {attempt} 次)", level="INFO")

        try:
            executor = ExecutorRegistry.get(info["script"].runner)
            result = executor.execute(
                execution, info["version"], execution.params, timeout=info["timeout"]
            )
            execution.status = result.status
            execution.result_code = result.result_code
            execution.error_message = result.error_message
        except Exception as exc:  # 执行器异常兜底
            execution.status = Execution.Status.FAILED
            execution.error_message = f"{type(exc).__name__}: {exc}"
            add_log(execution, execution.error_message, level="ERROR")

        if execution.status == Execution.Status.SUCCESS or attempt > max_retries:
            break
        execution.status = Execution.Status.RETRYING
        execution.retry_count = attempt
        execution.save(update_fields=["status", "retry_count", "updated_at"])
        add_log(
            execution,
            f"执行失败,将在 {retry_delay}s 后重试(第 {attempt}/{max_retries} 次)",
            level="WARNING",
        )
        if retry_delay > 0:
            time.sleep(retry_delay)

    execution.finished_at = timezone.now()
    if execution.started_at:
        execution.duration_ms = int(
            (execution.finished_at - execution.started_at).total_seconds() * 1000
        )
    execution.save(update_fields=_FINAL_FIELDS)

    level = "INFO" if execution.status == Execution.Status.SUCCESS else "ERROR"
    add_log(execution, f"执行结束: {execution.get_status_display()}", level=level)

    if execution.asset_type == Execution.AssetType.SCHEDULE:
        _update_schedule_stats(execution)
    elif execution.asset_type == Execution.AssetType.ENDPOINT:
        _update_endpoint_stats(execution)

    # 告警评估(执行结果:超时/连续失败);评估异常不影响执行结果
    try:
        from ops_platform.apps.alerts.evaluator import evaluate_execution

        evaluate_execution(execution)
    except Exception:
        pass

    return {
        "execution_id": execution_id,
        "status": execution.status,
        "retry_count": execution.retry_count,
    }


def _resolve_asset(execution) -> dict:
    """解析资产与执行配置:script / schedule。"""
    if execution.asset_type == Execution.AssetType.SCRIPT:
        script = Script.objects.get(pk=execution.asset_id)
        return {
            "script": script,
            "version": _resolve_current_version(script),
            "timeout": script.timeout_seconds,
            "max_retries": 0,
            "retry_delay": 0,
        }
    if execution.asset_type == Execution.AssetType.SCHEDULE:
        from ops_platform.apps.schedules.models import ScheduleTask

        schedule = ScheduleTask.objects.select_related("script").get(pk=execution.asset_id)
        return {
            "script": schedule.script,
            "version": _resolve_current_version(schedule.script),
            "timeout": schedule.effective_timeout,
            "max_retries": schedule.max_retries,
            "retry_delay": schedule.retry_delay,
        }
    if execution.asset_type == Execution.AssetType.ENDPOINT:
        from ops_platform.apps.endpoints.models import HttpEndpoint

        endpoint = HttpEndpoint.objects.select_related("script").get(pk=execution.asset_id)
        if endpoint.script_id is None:
            raise HttpEndpoint.DoesNotExist(
                f"接口 {endpoint.code} 未绑定脚本,无法执行"
            )
        return {
            "script": endpoint.script,
            "version": _resolve_current_version(endpoint.script),
            "timeout": endpoint.timeout or endpoint.script.timeout_seconds,
            "max_retries": 0,
            "retry_delay": 0,
        }
    raise NotImplementedError(f"不支持的资产类型: {execution.asset_type}")


def _resolve_current_version(script: Script):
    version = script.current_version_obj
    if version is None:
        raise Script.DoesNotExist(
            f"脚本 {script.code} 当前版本({script.current_version})不存在"
        )
    return version


def _update_schedule_stats(execution: Execution) -> None:
    """执行结束后回写定时任务统计:最近执行时间、连续失败次数。"""
    from ops_platform.apps.schedules.models import ScheduleTask

    schedule = ScheduleTask.objects.filter(pk=execution.asset_id).first()
    if schedule is None:
        return
    fields = {"last_run_at": execution.finished_at}
    if execution.status == Execution.Status.SUCCESS:
        fields["consecutive_failures"] = 0
    else:
        fields["consecutive_failures"] = schedule.consecutive_failures + 1
    ScheduleTask.objects.filter(pk=schedule.pk).update(**fields)


def _update_endpoint_stats(execution: Execution) -> None:
    """执行结束后回写接口调用记录(expose)与健康统计。"""
    from ops_platform.apps.endpoints.models import EndpointCallLog, HttpEndpoint
    from ops_platform.apps.endpoints.services import update_health_stats

    call = EndpointCallLog.objects.filter(request_id=execution.request_id).first()
    endpoint = HttpEndpoint.objects.filter(pk=execution.asset_id).first()
    if call is not None:
        call.success = execution.status == Execution.Status.SUCCESS
        call.response_ms = execution.duration_ms
        call.error_message = execution.error_message
        call.save(update_fields=["success", "response_ms", "error_message", "updated_at"])
    if endpoint is not None:
        update_health_stats(endpoint)
