from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timezone

from .coinbase_client import CoinbaseClient
from .config import BotConfig, load_config
from .storage import BotStorage
from .strategy import score_market


def run_cycle(config: BotConfig | None = None) -> dict:
    config = config or load_config()
    storage = BotStorage(config)
    client = CoinbaseClient(config)
    state_id = "live" if config.live_enabled else "paper"
    state = storage.load_state(state_id)
    today = datetime.now(timezone.utc).date().isoformat()
    base_currency, quote_currency = _product_currencies(config.product_id)

    if config.live_enabled and client._client:
        try:
            balances = client.get_available_balances()
            state["cash_usd"] = balances.get(quote_currency, float(state.get("cash_usd", 0) or 0))
            state["base_size"] = balances.get(base_currency, float(state.get("base_size", 0) or 0))
            state["last_balance_sync_at"] = now_iso()
        except Exception as exc:
            state["last_error"] = {"balance_sync": str(exc)}

    if state.get("daily_loss_date") != today:
        state["daily_loss_date"] = today
        state["daily_loss_usd"] = 0.0
        if state.get("halt_reason") == "Max daily loss reached.":
            state["halted"] = False
            state["halt_reason"] = None

    if state.get("halted"):
        state["last_cycle_at"] = now_iso()
        storage.save_state(state, state_id)
        result = {"mode": config.trading_mode, "action": "HALTED", "reason": state.get("halt_reason") or "Bot is halted by risk control or operator setting.", "state": state}
        storage.log_event("cycle", result)
        return result

    if abs(min(0.0, float(state.get("daily_loss_usd", 0)))) >= abs(config.max_daily_loss_usd):
        state["halted"] = True
        state["halt_reason"] = "Max daily loss reached."
        state["last_cycle_at"] = now_iso()
        storage.save_state(state, state_id)
        result = {"mode": config.trading_mode, "action": "HALTED", "reason": "Max daily loss reached.", "state": state}
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
    preview = None
    if signal.action == "BUY" and signal.confidence >= config.confidence_to_buy:
        trade_usd = min(config.max_trade_usd, float(state.get("cash_usd", 0)))
        if trade_usd >= config.min_trade_usd and signal.price > 0:
            fee = trade_usd * config.estimated_fee_pct
            preview = {
                "side": "BUY",
                "quote_size": trade_usd,
                "estimated_fee": fee,
                "estimated_base_size": max(0.0, trade_usd - fee) / signal.price,
                "price": signal.price,
                "reason": signal.reason,
            }
            storage.log_event("trade_attempt", {"mode": config.trading_mode, "product_id": config.product_id, "preview": preview, "signal": asdict(signal)})
            execution = client.place_market_buy(config.product_id, trade_usd)
            if execution.success:
                base_bought = (trade_usd - fee) / signal.price
                state["cash_usd"] = float(state.get("cash_usd", 0)) - trade_usd
                state["base_size"] = float(state.get("base_size", 0)) + base_bought
                state["entry_price"] = signal.price
                state["total_fees"] = float(state.get("total_fees", 0)) + (fee if not config.live_enabled else 0)
            storage.log_event("trade_result", {"mode": config.trading_mode, "product_id": config.product_id, "preview": preview, "execution": asdict(execution)})
    elif signal.action == "SELL" and signal.confidence >= config.confidence_to_sell and has_position:
        base_size = float(state.get("base_size", 0))
        quote_estimate = base_size * signal.price
        fee = quote_estimate * config.estimated_fee_pct
        preview = {
            "side": "SELL",
            "base_size": base_size,
            "quote_estimate": quote_estimate,
            "estimated_fee": fee,
            "net_quote_estimate": max(0.0, quote_estimate - fee),
            "price": signal.price,
            "reason": signal.reason,
        }
        storage.log_event("trade_attempt", {"mode": config.trading_mode, "product_id": config.product_id, "preview": preview, "signal": asdict(signal)})
        execution = client.place_market_sell(config.product_id, base_size, quote_estimate)
        if execution.success:
            entry_value = base_size * float(state.get("entry_price") or signal.price)
            net_quote = quote_estimate - fee
            pnl = net_quote - entry_value
            state["cash_usd"] = float(state.get("cash_usd", 0)) + net_quote
            state["base_size"] = 0.0
            state["entry_price"] = None
            state["realized_pnl"] = float(state.get("realized_pnl", 0)) + pnl
            state["daily_loss_usd"] = min(0.0, float(state.get("daily_loss_usd", 0)) + pnl)
            state["total_fees"] = float(state.get("total_fees", 0)) + (fee if not config.live_enabled else 0)
        storage.log_event("trade_result", {"mode": config.trading_mode, "product_id": config.product_id, "preview": preview, "execution": asdict(execution)})

    state["last_cycle_at"] = now_iso()
    state["last_action"] = signal.action
    state["last_error"] = None if not execution or execution.success else execution.response
    storage.save_state(state, state_id)
    result = {
        "mode": config.trading_mode,
        "product_id": config.product_id,
        "signal": asdict(signal),
        "preview": preview,
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _product_currencies(product_id: str) -> tuple[str, str]:
    pieces = product_id.split("-")
    if len(pieces) >= 2:
        return pieces[0], pieces[1]
    return product_id, "USD"
