from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


def _secret(secrets: Any, name: str, default: str = "") -> str:
    try:
        value = secrets.get(name, default)
    except Exception:
        value = default
    return str(os.getenv(name, value or default))


def _secret_float(secrets: Any, name: str, default: float) -> float:
    try:
        return float(_secret(secrets, name, str(default)))
    except ValueError:
        return default


def _secret_list(secrets: Any, name: str, default: list[str]) -> list[str]:
    value = _secret(secrets, name, ",".join(default))
    return [item.strip().upper() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class BotConfig:
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    trading_mode: str = "paper"
    product_id: str = "BTC-USD"
    watchlist: tuple[str, ...] = ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "ADA-USD", "AVAX-USD", "LINK-USD")
    auto_select_market: bool = True
    starting_cash: float = 100.0
    max_trade_usd: float = 15.0
    min_trade_usd: float = 5.0
    max_daily_loss_usd: float = 15.0
    stop_loss_pct: float = 0.035
    take_profit_pct: float = 0.07
    confidence_to_buy: float = 0.62
    confidence_to_sell: float = 0.54
    estimated_fee_pct: float = 0.006
    scan_market_limit: int = 40
    notification_webhook_url: str = ""
    cycle_seconds: int = 300

    @property
    def live_enabled(self) -> bool:
        return self.trading_mode.lower() == "live"


def load_config(secrets: Any | None = None) -> BotConfig:
    secrets = secrets or _load_local_streamlit_secrets()
    return BotConfig(
        coinbase_api_key=_secret(secrets, "COINBASE_API_KEY"),
        coinbase_api_secret=_secret(secrets, "COINBASE_API_SECRET"),
        supabase_url=_secret(secrets, "SUPABASE_URL"),
        supabase_anon_key=_secret(secrets, "SUPABASE_ANON_KEY"),
        trading_mode=_secret(secrets, "TRADING_MODE", "paper").lower(),
        product_id=_secret(secrets, "PRODUCT_ID", "BTC-USD"),
        watchlist=tuple(_secret_list(secrets, "WATCHLIST", ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "ADA-USD", "AVAX-USD", "LINK-USD"])),
        auto_select_market=_secret(secrets, "AUTO_SELECT_MARKET", "true").lower() in {"1", "true", "yes", "on"},
        starting_cash=_secret_float(secrets, "STARTING_CASH", 100.0),
        max_trade_usd=_secret_float(secrets, "MAX_TRADE_USD", 15.0),
        min_trade_usd=_secret_float(secrets, "MIN_TRADE_USD", 5.0),
        max_daily_loss_usd=_secret_float(secrets, "MAX_DAILY_LOSS_USD", 15.0),
        stop_loss_pct=_secret_float(secrets, "STOP_LOSS_PCT", 0.035),
        take_profit_pct=_secret_float(secrets, "TAKE_PROFIT_PCT", 0.07),
        confidence_to_buy=_secret_float(secrets, "CONFIDENCE_TO_BUY", 0.62),
        confidence_to_sell=_secret_float(secrets, "CONFIDENCE_TO_SELL", 0.54),
        estimated_fee_pct=_secret_float(secrets, "ESTIMATED_FEE_PCT", 0.006),
        scan_market_limit=int(_secret_float(secrets, "SCAN_MARKET_LIMIT", 40)),
        notification_webhook_url=_secret(secrets, "NOTIFICATION_WEBHOOK_URL"),
        cycle_seconds=int(_secret_float(secrets, "CYCLE_SECONDS", 300)),
    )


def _load_local_streamlit_secrets() -> dict[str, Any]:
    secrets_path = Path(".streamlit/secrets.toml")
    if not tomllib or not secrets_path.exists():
        return {}
    try:
        return tomllib.loads(secrets_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
