"""ops_sdk — 平台脚本侧 SDK。

被执行的脚本通过 `import ops_sdk` 使用(PYTHONPATH 已由执行器注入项目根):
- log():输出统一 JSON 日志行,平台流式采集结构化入库;
- get_param():读取平台注入并校验后的执行参数;
- mark_secret():标记敏感值,log() 输出时自动脱敏,防止敏感信息落库。

示例:
    import ops_sdk

    def main(params):
        ops_sdk.log("开始执行", level="INFO", target=params.get("host"))
        token = ops_sdk.mark_secret(params.get("token"))
        ops_sdk.log(f"连接 token={token}")   # 输出时脱敏为 ***
        return {"success": True}
"""
from __future__ import annotations

import json
import os
import time

__all__ = ["log", "get_param", "mark_secret"]

_SECRET_VALUES: set[str] = set()


def mark_secret(value):
    """标记敏感值(如 Token、密码),log() 输出时自动替换为 ***。"""
    if value is not None:
        _SECRET_VALUES.add(str(value))
    return value


def get_param(name, default=None):
    """读取平台注入的执行参数(来自 OPS_PARAMS_FILE,JSON)。"""
    path = os.environ.get("OPS_PARAMS_FILE")
    if not path:
        return default
    cache = getattr(get_param, "_cache", None)
    if cache is None:
        try:
            with open(path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
        get_param._cache = cache
    return cache.get(name, default)


def log(message: str, level: str = "INFO", **extra) -> None:
    """输出一行统一格式 JSON 日志(含敏感脱敏)。"""
    safe_message = _mask(message)
    safe_extra = {k: _mask(v) for k, v in extra.items()}
    record = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "task_id": os.environ.get("OPS_EXECUTION_ID", ""),
        "request_id": os.environ.get("OPS_REQUEST_ID", ""),
        "user": os.environ.get("OPS_USER", ""),
        "level": str(level).upper(),
        "node": os.environ.get("OPS_NODE", ""),
        "message": safe_message,
        "extra": safe_extra,
    }
    print(json.dumps(record, ensure_ascii=False), flush=True)


def _mask(value) -> str:
    text = str(value)
    for secret in _SECRET_VALUES:
        if secret:
            text = text.replace(secret, "***")
    return text
