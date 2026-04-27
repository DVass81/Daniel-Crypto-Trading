from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from .coinbase_client import CoinbaseClient
from .config import BotConfig
from .strategy import Signal, score_market


def rank_markets(client: CoinbaseClient, config: BotConfig, products: list[str] | None = None, limit: int = 12) -> list[dict[str, Any]]:
    product_ids = list(products or config.watchlist)
    rows: list[dict[str, Any]] = []
    for product_id in product_ids[:limit]:
        try:
            candles = client.get_candles(product_id)
            signal = score_market(candles, has_position=False, entry_price=None, stop_loss_pct=config.stop_loss_pct, take_profit_pct=config.take_profit_pct)
            rows.append(_rank_row(product_id, signal, candles))
        except Exception as exc:
            rows.append(
                {
                    "product_id": product_id,
                    "action": "ERROR",
                    "confidence": 0.0,
                    "price": 0.0,
                    "ai_score": 0.0,
                    "advice": f"Could not score market: {exc}",
                }
            )
    return sorted(rows, key=lambda row: float(row.get("ai_score", 0)), reverse=True)


def best_buy_candidate(client: CoinbaseClient, config: BotConfig) -> dict[str, Any] | None:
    ranked = rank_markets(client, config, limit=len(config.watchlist))
    for row in ranked:
        if row["action"] == "BUY" and float(row["confidence"]) >= config.confidence_to_buy:
            return row
    return ranked[0] if ranked else None


def ai_advice(row: dict[str, Any], config: BotConfig) -> str:
    action = row.get("action")
    confidence = float(row.get("confidence") or 0)
    product_id = row.get("product_id")
    if action == "BUY" and confidence >= config.confidence_to_buy:
        return f"{product_id}: buy candidate. Confidence is above the current threshold; use position limits and stop loss."
    if action == "SELL" and confidence >= config.confidence_to_sell:
        return f"{product_id}: sell/risk-off signal. The model sees weakening conditions or risk limit pressure."
    if action == "ERROR":
        return str(row.get("advice") or "Unable to analyze this market.")
    return f"{product_id}: watchlist only. Conditions are not strong enough for an automated entry."


def _rank_row(product_id: str, signal: Signal, candles: pd.DataFrame) -> dict[str, Any]:
    metrics = signal.metrics or {}
    volatility = float(metrics.get("volatility_20", 0) or 0)
    momentum = float(metrics.get("momentum_6", 0) or 0)
    trend_bonus = 0.08 if float(metrics.get("ema_fast", 0) or 0) > float(metrics.get("ema_slow", 0) or 0) else 0
    risk_penalty = min(0.25, volatility * 8)
    ai_score = max(0.0, min(1.0, float(signal.confidence) + trend_bonus + max(0.0, momentum * 2) - risk_penalty))
    row = {
        "product_id": product_id,
        "action": signal.action,
        "confidence": signal.confidence,
        "price": signal.price,
        "ai_score": ai_score,
        "reason": signal.reason,
        **{f"metric_{key}": value for key, value in metrics.items()},
    }
    row["advice"] = _plain_advice(row)
    return row


def _plain_advice(row: dict[str, Any]) -> str:
    if row["action"] == "BUY":
        return "Trend and momentum are constructive. Consider only within risk limits."
    if row["action"] == "SELL":
        return "Risk-off signal. Avoid new buys or protect an open position."
    return "No strong edge. Watch and wait."
