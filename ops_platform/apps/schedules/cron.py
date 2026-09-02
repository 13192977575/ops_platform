"""标准 5 段 Cron 表达式解析与校验,转换为 django-celery-beat CrontabSchedule 字段。

支持形态:*, n, a-b, a/b, */b, a,b,c(可组合范围与步进)。
周字段兼容 cron 约定:0 与 7 均表示周日(beat 使用 0-6)。
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"^(\*|\d+)(?:-(\d+))?(?:/(\d+))?$")


class CronParseError(ValueError):
    pass


def _validate_field(name: str, raw: str, low: int, high: int) -> None:
    for token in raw.split(","):
        if not token:
            raise CronParseError(f"{name} 字段存在空项: {raw!r}")
        if token == "*":
            continue
        m = _TOKEN_RE.match(token)
        if not m:
            raise CronParseError(f"{name} 字段非法: {token!r}")
        start_s, end_s, step_s = m.groups()
        if start_s == "*" and step_s is None:
            raise CronParseError(f"{name} 字段非法: {token!r}")
        if start_s != "*":
            start = int(start_s)
            if not (low <= start <= high):
                raise CronParseError(f"{name} 字段越界(应为 {low}-{high}): {token!r}")
        if end_s is not None:
            end = int(end_s)
            if not (low <= end <= high) or (start_s != "*" and end < int(start_s)):
                raise CronParseError(f"{name} 字段范围非法: {token!r}")
        if step_s is not None:
            if int(step_s) <= 0:
                raise CronParseError(f"{name} 字段步进必须为正数: {token!r}")


def _convert_dow(raw: str) -> str:
    """cron 周字段(0-7,0/7=周日)→ django-celery-beat(0-6)。"""
    out = []
    for token in raw.split(","):
        if token == "*" or "-" in token or "/" in token:
            out.append(token)
            continue
        v = int(token)
        out.append(str(0 if v == 7 else v))
    return ",".join(out)


def parse_cron(expr: str) -> dict[str, str]:
    """解析并校验 5 段 cron,返回 CrontabSchedule 字段字典。"""
    if not expr or not expr.strip():
        raise CronParseError("cron 表达式不能为空")
    parts = expr.strip().split()
    if len(parts) != 5:
        raise CronParseError("cron 表达式必须为 5 段(分 时 日 月 周)")
    minute, hour, dom, month, dow = parts
    _validate_field("分钟", minute, 0, 59)
    _validate_field("小时", hour, 0, 23)
    _validate_field("日", dom, 1, 31)
    _validate_field("月", month, 1, 12)
    _validate_field("周", dow, 0, 7)
    return {
        "minute": minute,
        "hour": hour,
        "day_of_month": dom,
        "month_of_year": month,
        "day_of_week": _convert_dow(dow),
    }
