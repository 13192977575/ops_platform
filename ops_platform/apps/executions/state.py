"""执行状态机:非法状态迁移直接抛异常,保证 Execution 状态流转可控。"""
from __future__ import annotations

from .models import Execution

TRANSITIONS: dict[str, set[str]] = {
    Execution.Status.PENDING: {Execution.Status.RUNNING, Execution.Status.CANCELED},
    Execution.Status.RETRYING: {Execution.Status.RUNNING},
    Execution.Status.RUNNING: {
        Execution.Status.SUCCESS,
        Execution.Status.FAILED,
        Execution.Status.TIMEOUT,
        Execution.Status.CANCELED,
    },
    # SUCCESS / FAILED / TIMEOUT / CANCELED 为终态
}


class InvalidTransitionError(ValueError):
    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"非法状态迁移: {current} → {target}")


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def assert_transition(execution: Execution, target: str) -> None:
    """校验并原地更新状态;非法迁移抛 InvalidTransitionError。"""
    if not can_transition(execution.status, target):
        raise InvalidTransitionError(execution.status, target)
    execution.status = target
