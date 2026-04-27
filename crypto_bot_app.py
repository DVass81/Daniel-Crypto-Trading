from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from crypto_bot.bot import run_cycle
from crypto_bot.coinbase_client import CoinbaseClient
from crypto_bot.config import load_config
from crypto_bot.storage import BotStorage
from crypto_bot.strategy import score_market

st.set_page_config(page_title="Crypto Bot Lab", page_icon="$", layout="wide")

STRATEGY_PROFILES = {
    "Conservative": {
        "max_trade_usd": 10.0,
        "max_daily_loss_usd": 8.0,
        "stop_loss_pct": 0.025,
        "take_profit_pct": 0.045,
        "confidence_to_buy": 0.72,
        "confidence_to_sell": 0.58,
    },
    "Balanced": {
        "max_trade_usd": 15.0,
        "max_daily_loss_usd": 15.0,
        "stop_loss_pct": 0.035,
        "take_profit_pct": 0.07,
        "confidence_to_buy": 0.62,
        "confidence_to_sell": 0.54,
    },
    "Aggressive": {
        "max_trade_usd": 25.0,
        "max_daily_loss_usd": 25.0,
        "stop_loss_pct": 0.055,
        "take_profit_pct": 0.11,
        "confidence_to_buy": 0.55,
        "confidence_to_sell": 0.50,
    },
}


def render_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.5rem; max-width: 1280px; }
        div[data-testid="stMetric"] {
            background: #0b131d;
            border: 1px solid #263748;
            border-radius: 8px;
            padding: 14px 16px;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
        }
        div[data-testid="stMetric"] label { color: #a7b2bf; }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] { color: #f5f7fa; }
        .status-row {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 8px 0 18px;
        }
        .badge {
            border-radius: 999px;
            padding: 6px 10px;
            font-size: 0.78rem;
            font-weight: 700;
            border: 1px solid rgba(255,255,255,0.14);
        }
        .badge.good { background: rgba(48, 168, 99, 0.18); color: #78e0a0; }
        .badge.warn { background: rgba(230, 161, 61, 0.18); color: #ffd082; }
        .badge.bad { background: rgba(220, 75, 75, 0.18); color: #ff9a9a; }
        .hero {
            border: 1px solid #253446;
            border-radius: 8px;
            padding: 18px 20px;
            background: linear-gradient(135deg, #09111a 0%, #102133 54%, #0c3428 100%);
            margin-bottom: 14px;
        }
        .hero h1 { margin: 0; color: #f7fafc; font-size: 2rem; letter-spacing: 0; }
        .hero p { margin: 6px 0 0; color: #b9c4cf; }
        .signal-box {
            border: 1px solid #253446;
            border-radius: 8px;
            padding: 16px;
            background: #0f1720;
        }
        .terminal-panel {
            border: 1px solid #253446;
            border-radius: 8px;
            padding: 12px 14px;
            background: #080f17;
        }
        .terminal-title {
            color: #8ea1b5;
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
            margin-bottom: 8px;
        }
        .terminal-value {
            color: #ecf3f8;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 1.1rem;
        }
        .small-muted { color: #9aa8b6; font-size: 0.86rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(label: str, tone: str) -> str:
    return f'<span class="badge {tone}">{label}</span>'


def fmt_money(value: float | int | None) -> str:
    return f"${float(value or 0):,.2f}"


def parse_time(value: Any) -> str:
    if not value:
        return "Never"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(value)


def flatten_event(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload") or {}
    signal = payload.get("signal") or {}
    execution = payload.get("execution") or {}
    state_payload = payload.get("state") or {}
    return {
        "created_at": parse_time(item.get("created_at")),
        "kind": item.get("kind"),
        "action": signal.get("action") or payload.get("action"),
        "confidence": signal.get("confidence"),
        "mode": payload.get("mode"),
        "price": signal.get("price"),
        "reason": signal.get("reason") or payload.get("reason"),
        "executed": bool(execution),
        "cash": state_payload.get("cash_usd"),
        "equity_payload": json.dumps(payload, default=str)[:900],
    }


def default_settings(config: Any) -> dict[str, Any]:
    return {
        "trading_mode": config.trading_mode,
        "strategy_profile": "Balanced",
        "max_trade_usd": config.max_trade_usd,
        "max_daily_loss_usd": config.max_daily_loss_usd,
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct,
        "confidence_to_buy": config.confidence_to_buy,
        "confidence_to_sell": config.confidence_to_sell,
    }


def get_settings(state: dict[str, Any], config: Any) -> dict[str, Any]:
    return {**default_settings(config), **(state.get("settings") or {})}


def save_settings(storage: BotStorage, state: dict[str, Any], settings: dict[str, Any]) -> None:
    state["settings"] = settings
    storage.save_state(state)


def config_with_settings(config: Any, settings: dict[str, Any]) -> Any:
    return replace(
        config,
        trading_mode=str(settings["trading_mode"]).lower(),
        max_trade_usd=float(settings["max_trade_usd"]),
        max_daily_loss_usd=float(settings["max_daily_loss_usd"]),
        stop_loss_pct=float(settings["stop_loss_pct"]),
        take_profit_pct=float(settings["take_profit_pct"]),
        confidence_to_buy=float(settings["confidence_to_buy"]),
        confidence_to_sell=float(settings["confidence_to_sell"]),
    )


def equity_history(events: list[dict[str, Any]], starting_cash: float) -> pd.DataFrame:
    rows = []
    for item in reversed(events):
        payload = item.get("payload") or {}
        signal = payload.get("signal") or {}
        state_payload = payload.get("state") or {}
        price = float(signal.get("price") or 0)
        cash = float(state_payload.get("cash_usd") or starting_cash)
        base = float(state_payload.get("base_size") or 0)
        rows.append(
            {
                "time": parse_time(item.get("created_at")),
                "equity": cash + (base * price),
            }
        )
    return pd.DataFrame(rows)


render_css()

base_config = load_config(st.secrets)
storage = BotStorage(base_config)
state = storage.load_state()
settings = get_settings(state, base_config)
config = config_with_settings(base_config, settings)
client = CoinbaseClient(config)
events = storage.list_events()

coinbase_configured = bool(config.coinbase_api_key and config.coinbase_api_secret)
supabase_configured = bool(config.supabase_url and config.supabase_anon_key)
supabase_connected = bool(storage._supabase)
coinbase_client_ready = bool(client._client)
halted = bool(state.get("halted"))

st.markdown(
    """
    <div class="hero">
        <h1>Crypto Bot Lab</h1>
        <p>Coinbase automation console with paper trading, signal scoring, Supabase logging, and hard risk controls.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

mode_tone = "good" if config.trading_mode == "paper" else "bad"
status_html = [
    badge(f"Mode: {config.trading_mode.upper()}", mode_tone),
    badge(f"Market: {config.product_id}", "good"),
    badge("Coinbase key loaded" if coinbase_configured else "Coinbase key missing", "good" if coinbase_configured else "warn"),
    badge("Coinbase SDK ready" if coinbase_client_ready else "Public market data only", "good" if coinbase_client_ready else "warn"),
    badge("Supabase connected" if supabase_connected else "Local fallback storage", "good" if supabase_connected else "warn"),
    badge("Emergency halt on" if halted else "Bot active", "bad" if halted else "good"),
]
st.markdown(f'<div class="status-row">{"".join(status_html)}</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Bot Controls")
    st.write(f"Product: `{config.product_id}`")
    st.write(f"Strategy: `{settings['strategy_profile']}`")
    st.write(f"Cycle interval: `{config.cycle_seconds}s`")
    st.write(f"Max trade: `{fmt_money(config.max_trade_usd)}`")
    st.write(f"Daily loss stop: `{fmt_money(config.max_daily_loss_usd)}`")

    st.divider()
    target_live = st.toggle("Live trading mode", value=config.live_enabled)
    if target_live != config.live_enabled:
        if target_live:
            st.warning("Live mode can place real Coinbase orders.")
            live_mode_ack = st.text_input("Type I ACCEPT THE RISK to enable live mode")
            if st.button("Confirm Live Mode"):
                if live_mode_ack == "I ACCEPT THE RISK" and coinbase_client_ready:
                    settings["trading_mode"] = "live"
                    save_settings(storage, state, settings)
                    st.rerun()
                elif not coinbase_client_ready:
                    st.error("Coinbase credentials are not ready.")
                else:
                    st.error("Confirmation text did not match.")
        else:
            settings["trading_mode"] = "paper"
            save_settings(storage, state, settings)
            st.rerun()

    live_ack = True
    if config.live_enabled:
        st.error("Live mode is enabled. Manual cycles require confirmation.")
        live_ack = st.text_input("Type I ACCEPT THE RISK") == "I ACCEPT THE RISK"

    if st.button("Run One Bot Cycle", type="primary", disabled=config.live_enabled and not live_ack):
        with st.spinner("Scoring market and applying bot rules..."):
            st.session_state["last_result"] = run_cycle(config)
            st.rerun()

    new_halted = st.toggle("Emergency halt", value=halted)
    if new_halted != halted:
        state["halted"] = new_halted
        storage.save_state(state)
        st.rerun()

    if st.button("Refresh Dashboard"):
        st.rerun()

cash = float(state.get("cash_usd", 0))
base = float(state.get("base_size", 0))
entry_price = state.get("entry_price")
price = 0.0
price_error = None

try:
    price = client.get_spot_price(config.product_id)
except Exception as exc:
    price_error = str(exc)

equity = cash + (base * price)
unrealized_pnl = (base * price) - (base * float(entry_price or price or 0))
realized_pnl = float(state.get("realized_pnl", 0) or 0)
total_pnl = equity - config.starting_cash
daily_loss_used = abs(min(0.0, float(state.get("daily_loss_usd", 0) or 0)))
daily_loss_ratio = min(1.0, daily_loss_used / max(config.max_daily_loss_usd, 0.01))

if price_error:
    st.warning(f"Price fetch failed: {price_error}")

metric_cols = st.columns(5)
metric_cols[0].metric("Estimated Equity", fmt_money(equity), f"{total_pnl:+.2f}")
metric_cols[1].metric("Cash", fmt_money(cash))
metric_cols[2].metric("Open Position", f"{base:.8f}")
metric_cols[3].metric("Spot Price", fmt_money(price) if price else "N/A")
metric_cols[4].metric("Realized P/L", fmt_money(realized_pnl))

try:
    candles = client.get_candles(config.product_id)
except Exception as exc:
    candles = pd.DataFrame()
    st.error(f"Candle fetch failed: {exc}")

signal = score_market(
    candles,
    has_position=base > 0,
    entry_price=entry_price,
    stop_loss_pct=config.stop_loss_pct,
    take_profit_pct=config.take_profit_pct,
)

overview_tab, signal_tab, events_tab, risk_tab, setup_tab = st.tabs(
    ["Overview", "Signal", "Events", "Risk", "Setup"]
)

with overview_tab:
    left, right = st.columns([2.2, 1])
    with left:
        st.subheader("Market Price")
        if not candles.empty:
            chart_frame = candles.set_index("time")[["close"]].rename(columns={"close": "Close"})
            st.line_chart(chart_frame, use_container_width=True, height=360)
        else:
            st.info("No candle data available yet.")

        history_frame = equity_history(events, config.starting_cash)
        if not history_frame.empty:
            st.subheader("Paper Equity Curve")
            st.line_chart(history_frame.set_index("time"), use_container_width=True, height=220)
    with right:
        st.subheader("Current Decision")
        st.markdown('<div class="signal-box">', unsafe_allow_html=True)
        st.metric("Action", signal.action)
        st.metric("Confidence", f"{signal.confidence:.2%}")
        st.write(signal.reason)
        st.markdown("</div>", unsafe_allow_html=True)

        st.subheader("Position")
        st.metric("Entry Price", fmt_money(entry_price) if entry_price else "No open entry")
        st.metric("Unrealized P/L", fmt_money(unrealized_pnl), f"{((price / entry_price - 1) * 100):+.2f}%" if entry_price and price else None)

with signal_tab:
    st.subheader("Signal Metrics")
    metric_rows = [
        {"metric": key, "value": value}
        for key, value in signal.metrics.items()
    ]
    if metric_rows:
        st.dataframe(metric_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Signal metrics will appear after enough candle history is available.")

    st.subheader("Bot Rules")
    rules = pd.DataFrame(
        [
            {"rule": "Buy confidence threshold", "value": f"{config.confidence_to_buy:.2%}"},
            {"rule": "Sell confidence threshold", "value": f"{config.confidence_to_sell:.2%}"},
            {"rule": "Stop loss", "value": f"{config.stop_loss_pct:.2%}"},
            {"rule": "Take profit", "value": f"{config.take_profit_pct:.2%}"},
            {"rule": "Minimum trade", "value": fmt_money(config.min_trade_usd)},
            {"rule": "Maximum trade", "value": fmt_money(config.max_trade_usd)},
        ]
    )
    st.dataframe(rules, use_container_width=True, hide_index=True)

with events_tab:
    st.subheader("Bot Event History")
    rows = [flatten_event(item) for item in events]
    if rows:
        event_frame = pd.DataFrame(rows)
        action_options = sorted([value for value in event_frame["action"].dropna().unique()])
        selected_actions = st.multiselect("Filter by action", action_options, default=action_options)
        if selected_actions:
            event_frame = event_frame[event_frame["action"].isin(selected_actions)]
        st.dataframe(event_frame, use_container_width=True, hide_index=True)
    else:
        st.info("No events logged yet. Run one bot cycle to create the first record.")

    if "last_result" in st.session_state:
        with st.expander("Last Cycle Payload"):
            st.json(st.session_state["last_result"])

with risk_tab:
    st.subheader("Risk Dashboard")
    risk_cols = st.columns(4)
    risk_cols[0].metric("Daily Loss Used", fmt_money(daily_loss_used))
    risk_cols[1].metric("Daily Loss Limit", fmt_money(config.max_daily_loss_usd))
    risk_cols[2].metric("Trade Cap", fmt_money(config.max_trade_usd))
    risk_cols[3].metric("Halt Status", "Halted" if halted else "Active")
    st.progress(daily_loss_ratio, text=f"Daily loss usage: {daily_loss_ratio:.0%}")

    warnings = []
    if config.live_enabled:
        warnings.append("Live trading is enabled. Keep max trade size low until paper results look stable.")
    if config.max_trade_usd > config.starting_cash * 0.25:
        warnings.append("Max trade size is more than 25% of starting cash.")
    if not supabase_connected:
        warnings.append("Supabase is not connected, so cloud logs may not persist.")
    if not coinbase_client_ready and coinbase_configured:
        warnings.append("Coinbase credentials are present but the SDK client did not initialize.")
    if warnings:
        for warning in warnings:
            st.warning(warning)
    else:
        st.success("Risk settings look reasonable for paper testing.")

    st.subheader("Runtime Settings")
    selected_profile = st.selectbox(
        "Strategy profile",
        list(STRATEGY_PROFILES),
        index=list(STRATEGY_PROFILES).index(str(settings.get("strategy_profile", "Balanced"))),
    )
    profile_values = STRATEGY_PROFILES[selected_profile]
    if selected_profile != settings.get("strategy_profile"):
        settings = {**settings, "strategy_profile": selected_profile, **profile_values}
        save_settings(storage, state, settings)
        st.rerun()

    with st.form("risk_settings_form"):
        new_max_trade = st.number_input("Max trade USD", min_value=1.0, max_value=100.0, value=float(settings["max_trade_usd"]), step=1.0)
        new_daily_loss = st.number_input("Max daily loss USD", min_value=1.0, max_value=100.0, value=float(settings["max_daily_loss_usd"]), step=1.0)
        new_stop_loss = st.slider("Stop loss", min_value=0.005, max_value=0.20, value=float(settings["stop_loss_pct"]), step=0.005, format="%.3f")
        new_take_profit = st.slider("Take profit", min_value=0.005, max_value=0.30, value=float(settings["take_profit_pct"]), step=0.005, format="%.3f")
        new_buy_conf = st.slider("Buy confidence", min_value=0.40, max_value=0.95, value=float(settings["confidence_to_buy"]), step=0.01)
        new_sell_conf = st.slider("Sell confidence", min_value=0.40, max_value=0.95, value=float(settings["confidence_to_sell"]), step=0.01)
        if st.form_submit_button("Save Runtime Settings", type="primary"):
            settings.update(
                {
                    "strategy_profile": selected_profile,
                    "max_trade_usd": new_max_trade,
                    "max_daily_loss_usd": new_daily_loss,
                    "stop_loss_pct": new_stop_loss,
                    "take_profit_pct": new_take_profit,
                    "confidence_to_buy": new_buy_conf,
                    "confidence_to_sell": new_sell_conf,
                }
            )
            save_settings(storage, state, settings)
            st.success("Settings saved.")
            st.rerun()

with setup_tab:
    st.subheader("Deployment Health")
    health = pd.DataFrame(
        [
            {"item": "Supabase URL", "status": "Configured" if config.supabase_url else "Missing"},
            {"item": "Supabase key", "status": "Configured" if config.supabase_anon_key else "Missing"},
            {"item": "Coinbase API key", "status": "Configured" if config.coinbase_api_key else "Missing"},
            {"item": "Coinbase private key", "status": "Configured" if config.coinbase_api_secret else "Missing"},
            {"item": "Trading mode", "status": config.trading_mode.upper()},
            {"item": "Last state update", "status": parse_time(state.get("updated_at"))},
        ]
    )
    st.dataframe(health, use_container_width=True, hide_index=True)

    st.subheader("Coinbase Account Check")
    if st.button("Test Coinbase Account Read"):
        if not coinbase_client_ready:
            st.error("Coinbase client is not ready. Check API key name and private key formatting.")
        else:
            try:
                accounts = client.get_accounts()
                if accounts:
                    st.success(f"Connected. Coinbase returned {len(accounts)} account records.")
                    st.dataframe(pd.DataFrame(accounts), use_container_width=True, hide_index=True)
                else:
                    st.warning("Connected, but no account records were returned.")
            except Exception as exc:
                st.error(f"Coinbase account read failed: {exc}")

    st.subheader("Suggested Next Upgrades")
    st.write(
        "Add authenticated balance checks, a paper-trade equity curve, configurable strategies, and an always-on runner before switching to live orders."
    )
