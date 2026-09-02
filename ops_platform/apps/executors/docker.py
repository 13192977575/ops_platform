"""Docker 隔离执行器:runner 格式 docker:image[:tag](D3 二期:容器级隔离)。

- 代码与参数写入临时目录,挂载到容器 /workspace,镜像内 python 执行;
- 资源限制:内存 -m、CPU --cpus(来自 Script.memory_limit_mb / cpu_limit);
- 超时:docker kill <container> 清理容器 + 终止 docker CLI 进程树;
- stdout 流式采集,逐行结构化入库(与本地执行器一致)。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from ops_platform.apps.executions.models import Execution
from ops_platform.apps.logs.services import add_log, log_stdout_line

from .base import BaseExecutor, ExecutionResult
from .local import _write_files, terminate_process_tree

_WORKDIR = "/workspace"


class DockerExecutor(BaseExecutor):
    name = "docker"

    def execute(self, execution, script_version, params: dict, timeout: int) -> ExecutionResult:
        script = script_version.script
        runner = getattr(script, "runner", "") or ""
        image = runner.split(":", 1)[1] if ":" in runner else ""
        if not image:
            msg = "docker runner 格式错误,应为 docker:image[:tag]"
            add_log(execution, msg, level="ERROR")
            return ExecutionResult(status=Execution.Status.FAILED, error_message=msg)

        started = time.monotonic()
        node = socket.gethostname()
        container_name = f"ops-exec-{execution.pk}"

        with tempfile.TemporaryDirectory(prefix="ops_docker_") as tmp:
            tmp_path = Path(tmp)
            params_file = tmp_path / "params.json"
            _write_files(tmp_path, script_version)
            params_file.write_text(
                json.dumps(params or {}, ensure_ascii=False), encoding="utf-8"
            )

            cmd = [
                "docker", "run", "--rm",
                "--name", container_name,
                "-v", f"{tmp_path}:{_WORKDIR}",
                "-w", _WORKDIR,
            ]
            cmd += _resource_args(script)
            # 脚本环境变量(解密,取脚本当前值)先注入;OPS_* 平台变量 setdefault 优先
            env = {"OPS_EXECUTION_ID": str(execution.pk),
                   "OPS_REQUEST_ID": execution.request_id or "",
                   "OPS_USER": _trigger_username(execution),
                   "OPS_NODE": node,
                   "OPS_PARAMS_FILE": f"{_WORKDIR}/params.json"}
            for key, value in script_version.script.get_env_vars().items():
                if value is not None:
                    env.setdefault(key, str(value))
            for key, value in env.items():
                cmd += ["-e", f"{key}={value}"]
            cmd += [image, "python", f"{_WORKDIR}/main.py"]

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    start_new_session=sys.platform != "win32",
                )
            except OSError as exc:
                msg = f"启动 docker 失败: {exc}"
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
                # 清理容器并终止 CLI 进程
                subprocess.run(
                    ["docker", "kill", container_name], capture_output=True, check=False
                )
                terminate_process_tree(proc)
                proc.wait(timeout=30)
            reader.join(timeout=10)

            duration_ms = int((time.monotonic() - started) * 1000)
            if timed_out:
                msg = f"执行超时(>{timeout}s),已终止容器 {container_name}"
                add_log(execution, msg, level="ERROR", node=node)
                return ExecutionResult(
                    status=Execution.Status.TIMEOUT, error_message=msg, duration_ms=duration_ms
                )
            if proc.returncode == 0:
                return ExecutionResult(
                    status=Execution.Status.SUCCESS, result_code=0, duration_ms=duration_ms
                )
            msg = f"容器退出码 {proc.returncode}"
            add_log(execution, msg, level="ERROR", node=node)
            return ExecutionResult(
                status=Execution.Status.FAILED,
                result_code=proc.returncode,
                error_message=msg,
                duration_ms=duration_ms,
            )


def _resource_args(script) -> list[str]:
    """按脚本资源限制生成 docker 参数(-m 内存 / --cpus CPU)。"""
    args: list[str] = []
    if getattr(script, "memory_limit_mb", None):
        args += ["-m", f"{script.memory_limit_mb}m"]
    if getattr(script, "cpu_limit", None):
        args += ["--cpus", str(script.cpu_limit)]
    return args


def _trigger_username(execution) -> str:
    user = getattr(execution, "trigger_user", None)
    return getattr(user, "username", "") if user else ""
