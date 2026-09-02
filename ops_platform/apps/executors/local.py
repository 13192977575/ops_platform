"""本地进程执行器(D3 一期:进程级隔离)。

- 代码与参数写入临时目录,子进程执行,平台脚本进程互不干扰;
- 超时强制终止进程树(Windows: taskkill /T,posix: 进程组 SIGKILL);
- stdout/stderr 流式采集,逐行结构化入库(统一 JSON 行优先解析);
- 通过环境变量注入执行上下文(OPS_EXECUTION_ID 等),PYTHONPATH 注入 SDK。
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from django.conf import settings

from ops_platform.apps.executions.models import Execution
from ops_platform.apps.logs.services import add_log, log_stdout_line

from .base import BaseExecutor, ExecutionResult

# runner 取值:空 / "python" / "python3" 时使用平台解释器(sys.executable)
_DEFAULT_RUNNERS = {"", "python", "python3"}


def terminate_process_tree(proc: subprocess.Popen) -> None:
    """终止进程树,防止超时后子进程残留。"""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except OSError:
                pass


class LocalProcessExecutor(BaseExecutor):
    name = "local"

    def execute(self, execution, script_version, params: dict, timeout: int) -> ExecutionResult:
        started = time.monotonic()
        node = socket.gethostname()
        with tempfile.TemporaryDirectory(prefix="ops_exec_") as tmp:
            tmp_path = Path(tmp)
            params_file = tmp_path / "params.json"
            _write_files(tmp_path, script_version)
            params_file.write_text(
                json.dumps(params or {}, ensure_ascii=False), encoding="utf-8"
            )

            runner = getattr(script_version.script, "runner", "") or ""
            cmd = [sys.executable if runner in _DEFAULT_RUNNERS else runner, str(script_file_path(tmp_path))]

            env = os.environ.copy()
            # 脚本环境变量(解密,取脚本当前值——修改后无需重建版本即可生效);
            # 先注入,平台 OPS_* 变量后注入,保证平台变量优先
            script_env = script_version.script.get_env_vars()
            env.update({k: str(v) for k, v in script_env.items() if v is not None})
            env.update(
                {
                    "OPS_EXECUTION_ID": str(execution.pk),
                    "OPS_REQUEST_ID": execution.request_id or "",
                    "OPS_USER": _trigger_username(execution),
                    "OPS_NODE": node,
                    "OPS_PARAMS_FILE": str(params_file),
                    "PYTHONPATH": str(settings.BASE_DIR),
                    # 强制子进程 stdout/stderr 使用 UTF-8,避免 Windows 管道下 cp936 乱码
                    "PYTHONIOENCODING": "utf-8",
                }
            )

            try:
                proc = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    start_new_session=sys.platform != "win32",
                    preexec_fn=_build_preexec_limit(script_version.script),
                )
            except OSError as exc:
                msg = f"启动执行进程失败: {exc}"
                add_log(execution, msg, level="ERROR", node=node)
                return ExecutionResult(
                    status=Execution.Status.FAILED,
                    error_message=msg,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )

            def pump():
                for line in iter(proc.stdout.readline, ""):
                    log_stdout_line(execution, line, node=node)

            reader = threading.Thread(target=pump, daemon=True)
            reader.start()

            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate_process_tree(proc)
                proc.wait(timeout=30)
            reader.join(timeout=10)

            duration_ms = int((time.monotonic() - started) * 1000)
            if timed_out:
                msg = f"执行超时(>{timeout}s),已强制终止"
                add_log(execution, msg, level="ERROR", node=node)
                return ExecutionResult(
                    status=Execution.Status.TIMEOUT,
                    error_message=msg,
                    duration_ms=duration_ms,
                )
            if proc.returncode == 0:
                return ExecutionResult(
                    status=Execution.Status.SUCCESS,
                    result_code=0,
                    duration_ms=duration_ms,
                )
            msg = f"进程退出码 {proc.returncode}"
            add_log(execution, msg, level="ERROR", node=node)
            return ExecutionResult(
                status=Execution.Status.FAILED,
                result_code=proc.returncode,
                error_message=msg,
                duration_ms=duration_ms,
            )


def _trigger_username(execution) -> str:
    user = getattr(execution, "trigger_user", None)
    return getattr(user, "username", "") if user else ""


def _write_files(tmp_path: Path, script_version) -> None:
    """写入主代码(main.py)与文件集(支持子目录),防路径穿越。

    文件集优先取版本快照;快照为空时回退到脚本当前 files(与 env_vars 一致,
    便于在 admin 主记录填写后立即可执行)。文件集内可含 .env 等非 .py 文件,
    脚本侧用 python-dotenv 自行加载。
    """
    main_file = tmp_path / "main.py"
    main_file.write_text(script_version.code or "", encoding="utf-8")
    files = script_version.files or []
    if not files:
        script = getattr(script_version, "script", None)
        if script is not None:
            files = script.files or []
    root = tmp_path.resolve()
    for item in files:
        if not isinstance(item, dict):
            continue
        rel_path = (item.get("path") or "").strip("/")
        content = item.get("content") or ""
        if not rel_path or rel_path == "main.py":
            continue
        target = (tmp_path / rel_path).resolve()
        if not str(target).startswith(str(root)):
            continue  # 拒绝路径穿越
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def script_file_path(tmp_path: Path) -> Path:
    """入口文件路径(主代码 main.py)。"""
    return tmp_path / "main.py"


def _build_preexec_limit(script):
    """POSIX 下为子进程应用资源限制(内存 RLIMIT_AS);Windows 返回 None(跳过)。

    CPU 核数限制仅由 Docker 执行器(--cpus)提供,本地进程不应用。
    """
    if sys.platform == "win32":
        return None
    memory_mb = getattr(script, "memory_limit_mb", None)
    if not memory_mb:
        return None
    limit_bytes = int(memory_mb) * 1024 * 1024

    def _apply_limit():
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))

    return _apply_limit
