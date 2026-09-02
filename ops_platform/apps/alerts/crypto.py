"""告警渠道凭据加密:复用 common.crypto(敏感键值 Fernet 加密存储)。

保留本模块作为兼容入口,实际实现见 ops_platform.apps.common.crypto。
"""
from __future__ import annotations

from ops_platform.apps.common.crypto import (  # noqa: F401
    decrypt_config,
    encrypt_config,
    _is_sensitive,
    _fernet,
)
