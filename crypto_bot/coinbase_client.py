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
        if config.coinbase_api_key and config.coinbase_api_secret:
            try:
                from coinbase.rest import RESTClient

                self._client = RESTClient(
                    api_key=config.coinbase_api_key,
                    api_secret=config.coinbase_api_secret,
                )
            except Exception:
                self._client = None

    def get_spot_price(self, product_id: str) -> float:
        if self._client:
            product = self._client.get_product(product_id)
            return float(_dictish(product).get("price", 0))

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
        raw = self._client.get_accounts()
        data = _dictish(raw)
        accounts = data.get("accounts", raw if isinstance(raw, list) else [])
        rows = []
        for account in accounts:
            item = _dictish(account)
            balance = _dictish(item.get("available_balance", {}))
            hold = _dictish(item.get("hold", {}))
            rows.append(
                {
                    "currency": item.get("currency"),
                    "available": balance.get("value"),
                    "available_currency": balance.get("currency"),
                    "hold": hold.get("value"),
                    "uuid": item.get("uuid"),
                }
            )
        return rows

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
