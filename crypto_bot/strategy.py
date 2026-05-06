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
    high = candles["high"].astype(float) if "high" in candles else close
    low = candles["low"].astype(float) if "low" in candles else close
    price = float(close.iloc[-1])
    ema_fast = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
    ema_slow = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
    ema_50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    momentum = float((price / close.iloc[-6]) - 1) if close.iloc[-6] else 0.0
    volatility = float(close.pct_change().tail(20).std() or 0.0)
    rsi = _rsi(close)
    macd, macd_signal, macd_hist = _macd(close)
    bb_mid, bb_upper, bb_lower, bb_width = _bollinger(close)
    atr = _atr(high, low, close)

    trend_score = _clamp((ema_fast / ema_slow - 1) * 35 + 0.5)
    momentum_score = _clamp(momentum * 18 + 0.5)
    rsi_score = _clamp((55 - abs(rsi - 55)) / 55)
    macd_score = 0.65 if macd_hist > 0 else 0.35
    bollinger_score = _clamp((price - bb_lower) / max(bb_upper - bb_lower, 0.000001))
    volatility_penalty = _clamp(volatility * 35)
    buy_confidence = _clamp(
        (trend_score * 0.34)
        + (momentum_score * 0.24)
        + (rsi_score * 0.16)
        + (macd_score * 0.16)
        + (bollinger_score * 0.10)
        - (volatility_penalty * 0.22)
    )

    metrics = {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_50": ema_50,
        "momentum_6": momentum,
        "volatility_20": volatility,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "bollinger_mid": bb_mid,
        "bollinger_upper": bb_upper,
        "bollinger_lower": bb_lower,
        "bollinger_width": bb_width,
        "atr": atr,
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


def _macd(close: pd.Series) -> tuple[float, float, float]:
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return float(macd_line.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])


def _bollinger(close: pd.Series, period: int = 20) -> tuple[float, float, float, float]:
    mid = close.rolling(period).mean().iloc[-1]
    std = close.rolling(period).std().iloc[-1]
    if pd.isna(mid) or pd.isna(std):
        price = float(close.iloc[-1])
        return price, price, price, 0.0
    upper = mid + (std * 2)
    lower = mid - (std * 2)
    width = (upper - lower) / mid if mid else 0.0
    return float(mid), float(upper), float(lower), float(width)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    prev_close = close.shift(1)
    true_range = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    value = true_range.rolling(period).mean().iloc[-1]
    return float(value) if pd.notna(value) else 0.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
