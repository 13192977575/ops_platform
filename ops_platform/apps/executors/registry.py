"""执行器注册表:按 runner 声明选择执行器,支持插件化扩展(D2 预留多节点)。"""
from __future__ import annotations

from .base import BaseExecutor


class ExecutorRegistry:
    _executors: dict[str, BaseExecutor] = {}

    @classmethod
    def register(cls, executor: BaseExecutor) -> None:
        cls._executors[executor.name] = executor

    @classmethod
    def get(cls, runner: str = "") -> BaseExecutor:
        """按 runner 解析执行器。

        - runner 以 "docker:" 开头 → Docker 隔离执行器;
        - runner 为解释器命令(如 python / python3 / 绝对路径)→ 本地进程执行器;
        - runner 以 "agent:" 开头 → 二期多节点 Agent 执行器(明确报错)。
        """
        if runner.startswith("docker:"):
            try:
                return cls._executors["docker"]
            except KeyError:
                raise RuntimeError("Docker 执行器(docker)未注册") from None
        if runner.startswith("agent:"):
            raise NotImplementedError("Agent 多节点执行器将在二期实现")
        try:
            return cls._executors["local"]
        except KeyError:
            raise RuntimeError("本地执行器(local)未注册") from None
