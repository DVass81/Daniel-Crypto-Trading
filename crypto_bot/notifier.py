from __future__ import annotations

from typing import Any

import requests

from .config import BotConfig
from .storage import BotStorage


def notify(storage: BotStorage, config: BotConfig, title: str, message: str, severity: str = "info", payload: dict[str, Any] | None = None) -> None:
    body = {
        "title": title,
        "message": message,
        "severity": severity,
        "payload": payload or {},
    }
    storage.log_event("notification", {"mode": config.trading_mode, **body})
    if not config.notification_webhook_url:
        return
    try:
        requests.post(config.notification_webhook_url, json=body, timeout=10)
    except Exception as exc:
        storage.log_event("notification_error", {"mode": config.trading_mode, "error": str(exc), "notification": body})
