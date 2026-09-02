"""执行器抽象:新增执行方式(如 Docker、Agent/SSH)只需实现 BaseExecutor 并注册。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionResult:
    """一次脚本执行的结果。status 取值对应 Execution.Status。"""

    status: str
    result_code: Optional[int] = None
    error_message: str = ""
    duration_ms: Optional[int] = None


class BaseExecutor(ABC):
    """执行器统一接口。"""

    name: str = "base"

    @abstractmethod
    def execute(self, execution, script_version, params: dict, timeout: int) -> ExecutionResult:
        """执行脚本并返回结果。

        :param execution: Execution 实例(状态已置 running)
        :param script_version: ScriptVersion 实例(代码与参数快照)
        :param params: 已校验归一化的参数 dict
        :param timeout: 超时秒数
        """
        raise NotImplementedError
