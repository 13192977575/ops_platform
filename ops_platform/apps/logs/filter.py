"""日志敏感信息过滤。

规则:
1. 命中敏感键值对(如 password=xxx / token: xxx)时,将值脱敏为 ***;
2. 额外字段(extra)的键名含敏感关键字时,整个值置为 ***;
3. 被 SDK mark_secret 标记的值,由 SDK 在输出前自行替换(见 ops_sdk)。
"""
from __future__ import annotations

import re

SENSITIVE_KEYWORDS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "apikey",
    "api_key",
    "access_key",
    "secret_key",
    "authorization",
    "cookie",
    "dsn",
    "connectionstring",
    "connection_string",
    "密码",
    "口令",
    "令牌",
    "密钥",
)

# 匹配 "key=value" 或 "key: value" 形式的敏感键值对
_KEY_VALUE_RE = re.compile(
    r"(?i)(password|passwd|token|secret|apikey|api[-_]?key|access[-_]?key|secret[-_]?key|"
    r"authorization|dsn|connection[-_]?string|密码|口令|令牌|密钥)\s*[:=]\s*[^\s,;\"']+"
)


def filter_sensitive(message: str, extra: dict | None = None) -> tuple[str, dict]:
    """对日志消息与附加字段执行脱敏,返回 (safe_message, safe_extra)。"""
    if not isinstance(message, str):
        message = str(message)
    if _KEY_VALUE_RE.search(message):
        message = _KEY_VALUE_RE.sub(r"\1=***", message)

    safe_extra: dict = {}
    for key, value in (extra or {}).items():
        lowered = str(key).lower()
        if any(kw in lowered for kw in SENSITIVE_KEYWORDS):
            safe_extra[key] = "***"
        elif isinstance(value, str) and _KEY_VALUE_RE.search(value):
            safe_extra[key] = _KEY_VALUE_RE.sub(r"\1=***", value)
        else:
            safe_extra[key] = value
    return message, safe_extra
