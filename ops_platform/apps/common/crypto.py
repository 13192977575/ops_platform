"""通用敏感字段加密工具(基于 Fernet):供告警渠道配置、脚本环境变量等复用。

- 敏感键(含 url/secret/token/password/key/cookie 等关键字)加密为 "enc:<ciphertext>";
- 非敏感键明文存储;读取时经 decrypt_config 还原;
- 密钥来自 settings.ALERT_ENCRYPTION_KEY(dev 固定默认,prod 强制环境变量)。
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

SENSITIVE_KEYWORDS = ("url", "secret", "token", "password", "key", "cookie")

_PREFIX = "enc:"


def _fernet() -> Fernet:
    key = getattr(settings, "ALERT_ENCRYPTION_KEY", "") or ""
    if not key:
        raise ImproperlyConfigured("必须设置 ALERT_ENCRYPTION_KEY(Fernet 密钥)")
    return Fernet(key.encode())


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(kw in lowered for kw in SENSITIVE_KEYWORDS)


def encrypt_config(config: dict) -> dict:
    """加密敏感键值,返回可落库的配置 dict。"""
    f = _fernet()
    out: dict = {}
    for key, value in (config or {}).items():
        if value is not None and _is_sensitive(key):
            cipher = f.encrypt(str(value).encode()).decode()
            out[key] = f"{_PREFIX}{cipher}"
        else:
            out[key] = value
    return out


def decrypt_config(config: dict) -> dict:
    """解密配置,返回明文 dict(供运行时使用)。"""
    f = _fernet()
    out: dict = {}
    for key, value in (config or {}).items():
        if isinstance(value, str) and value.startswith(_PREFIX):
            try:
                out[key] = f.decrypt(value[len(_PREFIX):].encode()).decode()
            except InvalidToken:
                out[key] = ""
        else:
            out[key] = value
    return out
