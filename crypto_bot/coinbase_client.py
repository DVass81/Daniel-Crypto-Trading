from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pandas as pd
import requests

from .config import BotConfig


@dataclass
class OrderResult:
    success: bool
    mode: str
    product_id: str
    side: str
    quote_size: float
    response: dict[str, Any]


class CoinbaseClient:
    """Thin wrapper around Coinbase Advanced Trade SDK with public REST fallback."""

    def __init__(self, config: BotConfig):
        self.config = config
        self._client = None
        self.init_error = ""
        if config.coinbase_api_key and config.coinbase_api_secret:
            try:
                from coinbase.rest import RESTClient

                self._client = RESTClient(
                    api_key=config.coinbase_api_key,
                    api_secret=config.coinbase_api_secret,
                )
            except Exception as exc:
                self._client = None
                self.init_error = str(exc)

    def get_spot_price(self, product_id: str) -> float:
        if self._client:
            product = self._client.get_product(product_id)
            return float(_field(product, "price", 0))

        url = f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}"
        data = requests.get(url, timeout=15).json()
        return float(data.get("price", 0))

    def get_products(self, limit: int = 250) -> list[dict[str, Any]]:
        if self._client:
            try:
                raw = self._client.get_products(limit=limit)
                data = _dictish(raw)
                products = data.get("products", raw if isinstance(raw, list) else [])
                return [_product_row(item) for item in products]
            except Exception:
                pass

        url = "https://api.coinbase.com/api/v3/brokerage/market/products"
        params = {"limit": limit}
        data = requests.get(url, params=params, timeout=20).json()
        products = data.get("products", [])
        return [_product_row(item) for item in products]

    def get_accounts(self) -> list[dict[str, Any]]:
        if not self._client:
            return []
        rows = []
        cursor = None
        seen_cursors = set()
        for _ in range(10):
            raw = self._get_accounts_page(cursor)
            accounts = _field(raw, "accounts", raw if isinstance(raw, list) else [])
            rows.extend([_account_row(account) for account in accounts])
            next_cursor = _field(raw, "cursor", None) or _field(raw, "next_cursor", None)
            has_next = _field(raw, "has_next", False)
            if not has_next or not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(str(next_cursor))
            cursor = next_cursor
        return rows

    def get_account_by_currency(self, currency: str) -> dict[str, Any] | None:
        target = currency.upper()
        for account in self.get_accounts():
            if str(account.get("currency") or "").upper() == target:
                return account
        return None

    def connection_diagnostics(self) -> dict[str, Any]:
        diagnostics = {
            "api_key_present": bool(self.config.coinbase_api_key),
            "api_secret_present": bool(self.config.coinbase_api_secret),
            "client_initialized": bool(self._client),
            "init_error": self.init_error,
            "account_count": 0,
            "nonzero_account_count": 0,
            "currencies_returned": "",
            "account_error": "",
        }
        if not self._client:
            return diagnostics
        try:
            accounts = self.get_accounts()
            diagnostics["account_count"] = len(accounts)
            diagnostics["nonzero_account_count"] = sum(1 for account in accounts if _to_float(account.get("available")) > 0)
            diagnostics["currencies_returned"] = ", ".join(sorted({str(account.get("currency") or "") for account in accounts if account.get("currency")}))
        except Exception as exc:
            diagnostics["account_error"] = str(exc)
        return diagnostics

    def _get_accounts_page(self, cursor: str | None = None) -> Any:
        call_attempts = []
        if cursor:
            call_attempts.extend(
                [
                    {"limit": 250, "cursor": cursor},
                    {"cursor": cursor},
                ]
            )
        call_attempts.extend([{"limit": 250}, {}])
        last_error = None
        for kwargs in call_attempts:
            try:
                return self._client.get_accounts(**kwargs)
            except TypeError as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        return self._client.get_accounts()

    def get_available_balances(self) -> dict[str, float]:
        balances: dict[str, float] = {}
        for account in self.get_accounts():
            currency = str(account.get("currency") or account.get("available_currency") or "")
            if not currency:
                continue
            try:
                balances[currency] = float(account.get("available") or 0)
            except (TypeError, ValueError):
                balances[currency] = 0.0
        return balances

    def get_candles(self, product_id: str, granularity: str = "FIFTEEN_MINUTE", limit: int = 96) -> pd.DataFrame:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=15 * limit)
        if self._client:
            raw = self._client.get_public_candles(
                product_id=product_id,
                start=str(int(start.timestamp())),
                end=str(int(end.timestamp())),
                granularity=granularity,
            )
            candles = _dictish(raw).get("candles", raw if isinstance(raw, list) else [])
        else:
            url = f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles"
            params = {
                "start": str(int(start.timestamp())),
                "end": str(int(end.timestamp())),
                "granularity": granularity,
            }
            candles = requests.get(url, params=params, timeout=15).json().get("candles", [])

        rows = [_dictish(candle) for candle in candles]
        frame = pd.DataFrame(rows)
        if frame.empty:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        rename_map = {"start": "time"}
        frame = frame.rename(columns=rename_map)
        for col in ["open", "high", "low", "close", "volume"]:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame["time"] = pd.to_datetime(pd.to_numeric(frame["time"], errors="coerce"), unit="s", utc=True)
        return frame.sort_values("time").dropna(subset=["close"])

    def place_market_buy(self, product_id: str, quote_size: float) -> OrderResult:
        if not self.config.live_enabled:
            return OrderResult(True, "paper", product_id, "BUY", quote_size, {"paper": True})
        if not self._client:
            return OrderResult(False, "live", product_id, "BUY", quote_size, {"error": "Coinbase client is not configured."})
        response = self._client.market_order_buy(
            client_order_id=str(uuid4()),
            product_id=product_id,
            quote_size=f"{quote_size:.2f}",
        )
        response_dict = _dictish(response)
        return OrderResult(bool(response_dict.get("success")), "live", product_id, "BUY", quote_size, response_dict)

    def place_market_sell(self, product_id: str, base_size: float, quote_estimate: float) -> OrderResult:
        if not self.config.live_enabled:
            return OrderResult(True, "paper", product_id, "SELL", quote_estimate, {"paper": True, "base_size": base_size})
        if not self._client:
            return OrderResult(False, "live", product_id, "SELL", quote_estimate, {"error": "Coinbase client is not configured."})
        response = self._client.market_order_sell(
            client_order_id=str(uuid4()),
            product_id=product_id,
            base_size=f"{base_size:.8f}",
        )
        response_dict = _dictish(response)
        return OrderResult(bool(response_dict.get("success")), "live", product_id, "SELL", quote_estimate, response_dict)


def _dictish(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    try:
        return dict(value)
    except Exception:
        return {}


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    if hasattr(value, name):
        return getattr(value, name)
    data = _dictish(value)
    return data.get(name, default)


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _account_row(account: Any) -> dict[str, Any]:
    balance = _field(account, "available_balance", {})
    hold = _field(account, "hold", {})
    currency = _field(account, "currency", "")
    available_value = _field(balance, "value", 0)
    available_currency = _field(balance, "currency", currency)
    hold_value = _field(hold, "value", 0)
    return {
        "currency": currency or available_currency,
        "available": available_value,
        "available_currency": available_currency,
        "hold": hold_value,
        "uuid": _field(account, "uuid", ""),
        "name": _field(account, "name", ""),
        "type": _field(account, "type", ""),
        "ready": _field(account, "ready", None),
        "active": _field(account, "active", None),
    }


def _product_row(value: Any) -> dict[str, Any]:
    item = _dictish(value)
    return {
        "product_id": item.get("product_id"),
        "base_currency_id": item.get("base_currency_id"),
        "quote_currency_id": item.get("quote_currency_id"),
        "price": item.get("price"),
        "price_percentage_change_24h": item.get("price_percentage_change_24h"),
        "volume_24h": item.get("volume_24h"),
        "volume_percentage_change_24h": item.get("volume_percentage_change_24h"),
        "status": item.get("status"),
        "trading_disabled": item.get("trading_disabled"),
    }
