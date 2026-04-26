from __future__ import annotations

import time
from dataclasses import asdict

from .coinbase_client import CoinbaseClient
from .config import BotConfig, load_config
from .storage import BotStorage
from .strategy import score_market


def run_cycle(config: BotConfig | None = None) -> dict:
    config = config or load_config()
    storage = BotStorage(config)
    client = CoinbaseClient(config)
    state = storage.load_state()

    if state.get("halted"):
        result = {"action": "HALTED", "reason": "Bot is halted by risk control or operator setting.", "state": state}
        storage.log_event("cycle", result)
        return result

    if float(state.get("daily_loss_usd", 0)) <= -abs(config.max_daily_loss_usd):
        state["halted"] = True
        storage.save_state(state)
        result = {"action": "HALTED", "reason": "Max daily loss reached.", "state": state}
        storage.log_event("risk_halt", result)
        return result

    candles = client.get_candles(config.product_id)
    has_position = float(state.get("base_size", 0) or 0) > 0
    signal = score_market(
        candles,
        has_position=has_position,
        entry_price=state.get("entry_price"),
        stop_loss_pct=config.stop_loss_pct,
        take_profit_pct=config.take_profit_pct,
    )

    execution = None
    if signal.action == "BUY" and signal.confidence >= config.confidence_to_buy:
        trade_usd = min(config.max_trade_usd, float(state.get("cash_usd", 0)))
        if trade_usd >= config.min_trade_usd and signal.price > 0:
            execution = client.place_market_buy(config.product_id, trade_usd)
            if execution.success:
                base_bought = trade_usd / signal.price
                state["cash_usd"] = float(state.get("cash_usd", 0)) - trade_usd
                state["base_size"] = float(state.get("base_size", 0)) + base_bought
                state["entry_price"] = signal.price
    elif signal.action == "SELL" and signal.confidence >= config.confidence_to_sell and has_position:
        base_size = float(state.get("base_size", 0))
        quote_estimate = base_size * signal.price
        execution = client.place_market_sell(config.product_id, base_size, quote_estimate)
        if execution.success:
            entry_value = base_size * float(state.get("entry_price") or signal.price)
            pnl = quote_estimate - entry_value
            state["cash_usd"] = float(state.get("cash_usd", 0)) + quote_estimate
            state["base_size"] = 0.0
            state["entry_price"] = None
            state["realized_pnl"] = float(state.get("realized_pnl", 0)) + pnl
            state["daily_loss_usd"] = min(0.0, float(state.get("daily_loss_usd", 0)) + pnl)

    storage.save_state(state)
    result = {
        "mode": config.trading_mode,
        "product_id": config.product_id,
        "signal": asdict(signal),
        "execution": asdict(execution) if execution else None,
        "state": state,
    }
    storage.log_event("cycle", result)
    return result


def run_forever(config: BotConfig | None = None) -> None:
    config = config or load_config()
    while True:
        run_cycle(config)
        time.sleep(max(30, config.cycle_seconds))
