from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Signal:
    action: str
    confidence: float
    price: float
    reason: str
    metrics: dict[str, float]


def score_market(candles: pd.DataFrame, has_position: bool, entry_price: float | None, stop_loss_pct: float, take_profit_pct: float) -> Signal:
    if candles.empty or len(candles) < 30:
        return Signal("HOLD", 0.0, 0.0, "Waiting for more candle history.", {})

    close = candles["close"].astype(float)
    price = float(close.iloc[-1])
    ema_fast = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
    ema_slow = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
    momentum = float((price / close.iloc[-6]) - 1) if close.iloc[-6] else 0.0
    volatility = float(close.pct_change().tail(20).std() or 0.0)
    rsi = _rsi(close)

    trend_score = _clamp((ema_fast / ema_slow - 1) * 35 + 0.5)
    momentum_score = _clamp(momentum * 18 + 0.5)
    rsi_score = _clamp((55 - abs(rsi - 55)) / 55)
    volatility_penalty = _clamp(volatility * 35)
    buy_confidence = _clamp((trend_score * 0.45) + (momentum_score * 0.35) + (rsi_score * 0.2) - (volatility_penalty * 0.25))

    metrics = {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "momentum_6": momentum,
        "volatility_20": volatility,
        "rsi": rsi,
        "buy_confidence": buy_confidence,
    }

    if has_position and entry_price:
        pnl_pct = (price / entry_price) - 1
        metrics["open_pnl_pct"] = pnl_pct
        if pnl_pct <= -abs(stop_loss_pct):
            return Signal("SELL", 0.95, price, "Stop loss reached.", metrics)
        if pnl_pct >= abs(take_profit_pct):
            return Signal("SELL", 0.88, price, "Take profit reached.", metrics)
        if ema_fast < ema_slow and momentum < 0:
            return Signal("SELL", _clamp(0.58 + abs(momentum * 6)), price, "Trend weakened while in a position.", metrics)
        return Signal("HOLD", buy_confidence, price, "Position is still within risk bands.", metrics)

    if buy_confidence > 0.5:
        return Signal("BUY", buy_confidence, price, "Trend, momentum, and RSI are aligned enough to consider entry.", metrics)
    return Signal("HOLD", buy_confidence, price, "No high-quality entry signal.", metrics)


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    value = 100 - (100 / (1 + rs.iloc[-1]))
    return float(value) if pd.notna(value) else 50.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
