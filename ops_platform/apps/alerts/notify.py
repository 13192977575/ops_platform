"""告警渠道发送服务:企业微信/钉钉机器人(webhook)、邮件(SMTP)、通用 Webhook。

凭据从渠道加密配置解密后使用;SMTP 参数走 Django 标准环境变量
(EMAIL_HOST/EMAIL_PORT/EMAIL_HOST_USER/EMAIL_HOST_PASSWORD/EMAIL_USE_TLS/DEFAULT_FROM_EMAIL)。
"""
from __future__ import annotations

import requests
from django.conf import settings

from .models import AlertChannel


def send(channel: AlertChannel, message: str, title: str | None = None) -> tuple[bool, str]:
    """发送告警到渠道,返回 (success, error)。"""
    config = channel.get_config()
    if channel.type == AlertChannel.ChannelType.WECOM:
        payload = {"msgtype": "text", "text": {"content": message}}
        return _send_webhook_json(config.get("webhook_url", ""), payload)
    if channel.type == AlertChannel.ChannelType.DINGTALK:
        payload = {"msgtype": "text", "text": {"content": message}}
        return _send_webhook_json(config.get("webhook_url", ""), payload)
    if channel.type == AlertChannel.ChannelType.WEBHOOK:
        payload = {"text": message, "title": title or ""}
        return _send_webhook_json(config.get("url", ""), payload)
    if channel.type == AlertChannel.ChannelType.EMAIL:
        return _send_email(config, message, title)
    return False, f"不支持的渠道类型: {channel.type}"


def _send_webhook_json(url: str, payload: dict) -> tuple[bool, str]:
    if not url:
        return False, "缺少 webhook url"
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code < 400:
            return True, ""
        return False, f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _send_email(config: dict, message: str, title: str | None) -> tuple[bool, str]:
    recipient = str(config.get("to", "")).strip()
    if not recipient:
        return False, "缺少收件人 to"
    if not getattr(settings, "EMAIL_HOST", ""):
        return False, "未配置 EMAIL_HOST(SMTP)"
    from django.core.mail import send_mail

    try:
        send_mail(
            subject=title or "运维自动化平台告警",
            message=message,
            from_email=None,  # 使用 settings.DEFAULT_FROM_EMAIL
            recipient_list=[recipient],
            fail_silently=False,
        )
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
