from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from crypto_bot.bot import run_cycle
from crypto_bot.coinbase_client import CoinbaseClient
from crypto_bot.config import BotConfig, load_config
from crypto_bot.market_ai import ai_advice, rank_all_usd_markets, rank_markets
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
        "estimated_fee_pct": 0.006,
    },
    "Balanced": {
        "max_trade_usd": 15.0,
        "max_daily_loss_usd": 15.0,
        "stop_loss_pct": 0.035,
        "take_profit_pct": 0.07,
        "confidence_to_buy": 0.62,
        "confidence_to_sell": 0.54,
        "estimated_fee_pct": 0.006,
    },
    "Aggressive": {
        "max_trade_usd": 25.0,
        "max_daily_loss_usd": 25.0,
        "stop_loss_pct": 0.055,
        "take_profit_pct": 0.11,
        "confidence_to_buy": 0.55,
        "confidence_to_sell": 0.50,
        "estimated_fee_pct": 0.006,
    },
}

DEFAULT_WATCHLIST = ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "ADA-USD", "AVAX-USD", "LINK-USD")


def render_css() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #070d14; }
        .block-container { padding-top: 1.25rem; max-width: 1320px; }
        div[data-testid="stMetric"] {
            background: #0c141f;
            border: 1px solid #263748;
            border-radius: 8px;
            padding: 13px 15px;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
        }
        div[data-testid="stMetric"] label { color: #9fb0c0; }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] { color: #f6f8fb; }
        .hero {
            border: 1px solid #263748;
            border-radius: 8px;
            padding: 18px 20px;
            background: linear-gradient(135deg, #071019 0%, #122235 58%, #0b3326 100%);
            margin-bottom: 10px;
        }
        .hero h1 { margin: 0; color: #f7fafc; font-size: 2rem; letter-spacing: 0; }
        .hero p { margin: 6px 0 0; color: #b9c4cf; }
        .status-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 14px; }
        .badge {
            border-radius: 999px;
            padding: 6px 10px;
            font-size: 0.78rem;
            font-weight: 700;
            border: 1px solid rgba(255,255,255,0.14);
            white-space: nowrap;
        }
        .good { background: rgba(48,168,99,.18); color: #78e0a0; }
        .warn { background: rgba(230,161,61,.18); color: #ffd082; }
        .bad { background: rgba(220,75,75,.18); color: #ff9a9a; }
        .neutral { background: rgba(120,145,170,.16); color: #cbd6e2; }
        .banner {
            border: 1px solid #263748;
            border-radius: 8px;
            padding: 12px 14px;
            margin: 8px 0 16px;
            font-weight: 700;
        }
        .banner.good { background: rgba(39,145,84,.16); }
        .banner.warn { background: rgba(230,161,61,.16); }
        .banner.bad { background: rgba(220,75,75,.16); }
        .panel {
            border: 1px solid #263748;
            border-radius: 8px;
            padding: 14px;
            background: #0a111a;
        }
        .trade-card {
            border-left: 4px solid #75869a;
            border-radius: 8px;
            padding: 10px 12px;
            background: #0c141f;
            margin-bottom: 8px;
        }
        .trade-card.buy { border-left-color: #4cc47c; }
        .trade-card.sell { border-left-color: #ff8a80; }
        .trade-card.hold { border-left-color: #8ea1b5; }
        .heat-cell {
            display: inline-block;
            min-width: 42px;
            margin: 3px;
            padding: 7px 5px;
            border-radius: 6px;
            text-align: center;
            font-size: .78rem;
            border: 1px solid rgba(255,255,255,.09);
        }
        @media (max-width: 720px) {
            .hero h1 { font-size: 1.55rem; }
            .badge { font-size: .72rem; padding: 5px 8px; }
            .block-container { padding-left: .8rem; padding-right: .8rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(label: str, tone: str) -> str:
    return f'<span class="badge {tone}">{label}</span>'


def fmt_money(value: float | int | None) -> str:
    return f"${float(value or 0):,.2f}"


def fmt_pct(value: float | int | None) -> str:
    return f"{float(value or 0):.2%}"


def parse_time(value: Any) -> str:
    if not value:
        return "Never"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(value)


def heartbeat_status(value: Any) -> tuple[str, str]:
    if not value:
        return "No heartbeat yet", "warn"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds()
    except ValueError:
        return "Heartbeat unknown", "warn"
    if age <= 600:
        return f"Runner fresh: {int(age // 60)} min ago", "good"
    if age <= 3600:
        return f"Runner stale: {int(age // 60)} min ago", "warn"
    return f"Runner offline: {int(age // 3600)} hr ago", "bad"


def default_settings(config: Any) -> dict[str, Any]:
    watchlist = getattr(config, "watchlist", DEFAULT_WATCHLIST)
    return {
        "trading_mode": getattr(config, "trading_mode", "paper"),
        "product_id": getattr(config, "product_id", "BTC-USD"),
        "watchlist": ",".join(watchlist),
        "auto_select_market": getattr(config, "auto_select_market", True),
        "strategy_profile": "Balanced",
        "max_trade_usd": getattr(config, "max_trade_usd", 15.0),
        "max_daily_loss_usd": getattr(config, "max_daily_loss_usd", 15.0),
        "stop_loss_pct": getattr(config, "stop_loss_pct", 0.035),
        "take_profit_pct": getattr(config, "take_profit_pct", 0.07),
        "confidence_to_buy": getattr(config, "confidence_to_buy", 0.62),
        "confidence_to_sell": getattr(config, "confidence_to_sell", 0.54),
        "estimated_fee_pct": getattr(config, "estimated_fee_pct", 0.006),
        "scan_market_limit": getattr(config, "scan_market_limit", 40),
    }


def get_settings(control_state: dict[str, Any], config: Any) -> dict[str, Any]:
    return {**default_settings(config), **(control_state.get("settings") or {})}


def save_settings(storage: BotStorage, control_state: dict[str, Any], settings: dict[str, Any]) -> None:
    control_state["settings"] = settings
    storage.save_state(control_state, "control")


def config_with_settings(config: Any, settings: dict[str, Any]) -> Any:
    watchlist = parse_watchlist(settings.get("watchlist") or ",".join(getattr(config, "watchlist", DEFAULT_WATCHLIST)))
    return BotConfig(
        coinbase_api_key=getattr(config, "coinbase_api_key", ""),
        coinbase_api_secret=getattr(config, "coinbase_api_secret", ""),
        supabase_url=getattr(config, "supabase_url", ""),
        supabase_anon_key=getattr(config, "supabase_anon_key", ""),
        trading_mode=str(settings["trading_mode"]).lower(),
        product_id=str(settings.get("product_id") or getattr(config, "product_id", "BTC-USD")).upper(),
        watchlist=tuple(watchlist or DEFAULT_WATCHLIST),
        auto_select_market=bool(settings.get("auto_select_market", getattr(config, "auto_select_market", True))),
        starting_cash=float(getattr(config, "starting_cash", 100.0)),
        max_trade_usd=float(settings["max_trade_usd"]),
        min_trade_usd=float(getattr(config, "min_trade_usd", 5.0)),
        max_daily_loss_usd=float(settings["max_daily_loss_usd"]),
        stop_loss_pct=float(settings["stop_loss_pct"]),
        take_profit_pct=float(settings["take_profit_pct"]),
        confidence_to_buy=float(settings["confidence_to_buy"]),
        confidence_to_sell=float(settings["confidence_to_sell"]),
        estimated_fee_pct=float(settings["estimated_fee_pct"]),
        scan_market_limit=int(settings.get("scan_market_limit", getattr(config, "scan_market_limit", 40))),
        notification_webhook_url=getattr(config, "notification_webhook_url", ""),
        cycle_seconds=int(getattr(config, "cycle_seconds", 300)),
    )


def parse_watchlist(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


def flatten_event(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload") or {}
    signal = payload.get("signal") or {}
    preview = payload.get("preview") or {}
    execution = payload.get("execution") or {}
    state_payload = payload.get("state") or {}
    return {
        "created_at": parse_time(item.get("created_at")),
        "kind": item.get("kind"),
        "mode": payload.get("mode"),
        "action": signal.get("action") or preview.get("side") or payload.get("action"),
        "confidence": signal.get("confidence"),
        "price": signal.get("price") or preview.get("price"),
        "executed": bool(execution),
        "cash": state_payload.get("cash_usd"),
        "reason": signal.get("reason") or preview.get("reason") or payload.get("reason"),
        "payload": json.dumps(payload, default=str)[:900],
    }


def equity_history(events: list[dict[str, Any]], mode: str, starting_cash: float) -> pd.DataFrame:
    rows = []
    for item in reversed(events):
        payload = item.get("payload") or {}
        if payload.get("mode") != mode:
            continue
        signal = payload.get("signal") or {}
        state_payload = payload.get("state") or {}
        if not state_payload:
            continue
        price = float(signal.get("price") or 0)
        cash = float(state_payload.get("cash_usd") or starting_cash)
        base = float(state_payload.get("base_size") or 0)
        rows.append({"time": parse_time(item.get("created_at")), "equity": cash + (base * price)})
    return pd.DataFrame(rows)


def daily_pnl(events: list[dict[str, Any]], mode: str, starting_cash: float) -> pd.DataFrame:
    history = equity_history(events, mode, starting_cash)
    if history.empty:
        return history
    history["day"] = history["time"].str.slice(0, 10)
    daily = history.groupby("day", as_index=False)["equity"].last()
    daily["pnl"] = daily["equity"].diff().fillna(daily["equity"] - starting_cash)
    return daily.tail(31)


def render_heatmap(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("P/L heatmap appears after paper cycles are logged.")
        return
    cells = []
    for _, row in frame.iterrows():
        pnl = float(row["pnl"])
        tone = "good" if pnl > 0 else "bad" if pnl < 0 else "neutral"
        cells.append(f'<span class="heat-cell {tone}">{row["day"][-5:]}<br>{pnl:+.2f}</span>')
    st.markdown("".join(cells), unsafe_allow_html=True)


def order_preview(signal: Any, state: dict[str, Any], config: Any) -> dict[str, Any] | None:
    cash = float(state.get("cash_usd", 0) or 0)
    base = float(state.get("base_size", 0) or 0)
    if signal.action == "BUY" and signal.confidence >= config.confidence_to_buy and signal.price:
        quote = min(config.max_trade_usd, cash)
        if quote < config.min_trade_usd:
            return None
        fee = quote * config.estimated_fee_pct
        return {"side": "BUY", "quote": quote, "fee": fee, "base": (quote - fee) / signal.price, "price": signal.price}
    if signal.action == "SELL" and signal.confidence >= config.confidence_to_sell and base > 0 and signal.price:
        quote = base * signal.price
        fee = quote * config.estimated_fee_pct
        return {"side": "SELL", "quote": quote, "fee": fee, "net": quote - fee, "base": base, "price": signal.price}
    return None


def load_market_rows(client: CoinbaseClient) -> pd.DataFrame:
    try:
        products = client.get_products(limit=250)
    except Exception:
        products = []
    frame = pd.DataFrame(products)
    if frame.empty:
        return frame
    for col in ["quote_currency_id", "trading_disabled", "product_id", "status"]:
        if col not in frame.columns:
            frame[col] = None
    for col in ["price", "price_percentage_change_24h", "volume_24h"]:
        if col not in frame.columns:
            frame[col] = 0
    frame = frame[frame["quote_currency_id"].eq("USD")]
    frame = frame[frame["trading_disabled"].ne(True)]
    for col in ["price", "price_percentage_change_24h", "volume_24h"]:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.sort_values("volume_24h", ascending=False, na_position="last")


def render_trade_cards(rows: list[dict[str, Any]]) -> None:
    trade_rows = [row for row in rows if row.get("kind") in {"trade_attempt", "trade_result", "cycle"}][:8]
    if not trade_rows:
        st.info("Trade cards appear after cycles are logged.")
        return
    for row in trade_rows:
        action = str(row.get("action") or "HOLD").lower()
        st.markdown(
            f"""
            <div class="trade-card {action}">
                <strong>{row.get("action") or "UNKNOWN"}</strong> - {row.get("kind")} - {row.get("created_at")}<br>
                <span style="color:#9fb0c0;">{row.get("reason") or "No reason recorded."}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_price_chart(candles: pd.DataFrame, product_id: str) -> None:
    if candles.empty:
        st.info("No candle data available yet.")
        return
    chart = candles.copy()
    chart["ema_9"] = chart["close"].ewm(span=9, adjust=False).mean()
    chart["ema_21"] = chart["close"].ewm(span=21, adjust=False).mean()
    chart["volume"] = pd.to_numeric(chart.get("volume", 0), errors="coerce")
    delta = chart["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    chart["rsi"] = 100 - (100 / (1 + rs))

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.64, 0.18, 0.18],
        vertical_spacing=0.035,
        specs=[[{"type": "candlestick"}], [{"type": "bar"}], [{"type": "scatter"}]],
    )
    fig.add_trace(
        go.Candlestick(
            x=chart["time"],
            open=chart["open"],
            high=chart["high"],
            low=chart["low"],
            close=chart["close"],
            name=product_id,
            increasing_line_color="#34c77b",
            decreasing_line_color="#ff6b6b",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(go.Scatter(x=chart["time"], y=chart["ema_9"], name="EMA 9", line={"color": "#6fb7ff", "width": 1.4}), row=1, col=1)
    fig.add_trace(go.Scatter(x=chart["time"], y=chart["ema_21"], name="EMA 21", line={"color": "#ffd166", "width": 1.4}), row=1, col=1)
    fig.add_trace(go.Bar(x=chart["time"], y=chart["volume"], name="Volume", marker_color="#30465d"), row=2, col=1)
    fig.add_trace(go.Scatter(x=chart["time"], y=chart["rsi"], name="RSI", line={"color": "#b794f4", "width": 1.4}), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ff8a80", row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#78e0a0", row=3, col=1)
    fig.update_layout(
        height=620,
        template="plotly_dark",
        paper_bgcolor="#070d14",
        plot_bgcolor="#0a111a",
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        xaxis_rangeslider_visible=False,
        legend_orientation="h",
        legend_y=1.04,
    )
    st.plotly_chart(fig, use_container_width=True)


def coinbase_portfolio_frame(client: CoinbaseClient) -> pd.DataFrame:
    accounts = client.get_accounts()
    rows = []
    for account in accounts:
        currency = str(account.get("currency") or account.get("available_currency") or "")
        amount = float(account.get("available") or 0)
        if amount <= 0:
            continue
        price = 1.0 if currency == "USD" else 0.0
        if currency != "USD":
            try:
                price = client.get_spot_price(f"{currency}-USD")
            except Exception:
                price = 0.0
        rows.append({"asset": currency, "amount": amount, "price_usd": price, "value_usd": amount * price})
    return pd.DataFrame(rows).sort_values("value_usd", ascending=False) if rows else pd.DataFrame()


def action_tone(action: str) -> str:
    action = action.upper()
    if action == "BUY":
        return "good"
    if action == "SELL":
        return "bad"
    return "neutral"


render_css()

base_config = load_config(st.secrets)
storage = BotStorage(base_config)
control_state = storage.load_state("control")
settings = get_settings(control_state, base_config)
config = config_with_settings(base_config, settings)
state_id = "live" if config.live_enabled else "paper"
state = storage.load_state(state_id)
client = CoinbaseClient(config)
events = storage.list_events(300)
active_product_id = state.get("product_id") or config.product_id

coinbase_configured = bool(config.coinbase_api_key and config.coinbase_api_secret)
coinbase_client_ready = bool(client._client)
supabase_connected = bool(storage._supabase)
halted = bool(state.get("halted"))
heartbeat_text, heartbeat_tone = heartbeat_status(state.get("last_cycle_at"))

st.markdown(
    """
    <div class="hero">
        <h1>Crypto Bot Lab</h1>
        <p>Trading console for paper testing, live-risk controls, Coinbase account checks, and Supabase history.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if halted:
    banner_tone, banner_text = "bad", f"HALTED: {state.get('halt_reason') or 'operator halt'}"
elif config.live_enabled:
    banner_tone, banner_text = "bad", "LIVE MODE ACTIVE: real Coinbase orders can be placed by bot cycles."
elif heartbeat_tone == "bad":
    banner_tone, banner_text = "warn", "PAPER MODE: bot runner heartbeat is stale."
else:
    banner_tone, banner_text = "good", "PAPER MODE: safe testing mode is active."
st.markdown(f'<div class="banner {banner_tone}">{banner_text}</div>', unsafe_allow_html=True)

status_html = [
    badge(f"Mode: {config.trading_mode.upper()}", "bad" if config.live_enabled else "good"),
    badge(f"State: {state_id}", "neutral"),
    badge(f"Market: {active_product_id}", "neutral"),
    badge("Auto-select on" if config.auto_select_market else "Fixed market", "good" if config.auto_select_market else "neutral"),
    badge("Coinbase key loaded" if coinbase_configured else "Coinbase key missing", "good" if coinbase_configured else "warn"),
    badge("Coinbase SDK ready" if coinbase_client_ready else "Public market data only", "good" if coinbase_client_ready else "warn"),
    badge("Supabase connected" if supabase_connected else "Local fallback storage", "good" if supabase_connected else "warn"),
    badge(heartbeat_text, heartbeat_tone),
]
st.markdown(f'<div class="status-row">{"".join(status_html)}</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Bot Controls")
    st.write(f"Active market: `{active_product_id}`")
    st.write(f"Strategy: `{settings['strategy_profile']}`")
    st.write(f"Max trade: `{fmt_money(config.max_trade_usd)}`")
    st.write(f"Daily loss stop: `{fmt_money(config.max_daily_loss_usd)}`")
    st.write(f"Fee model: `{fmt_pct(config.estimated_fee_pct)}`")

    st.divider()
    target_live = st.toggle("Live trading mode", value=config.live_enabled)
    if target_live != config.live_enabled:
        if target_live:
            st.warning("Live mode can place real Coinbase orders.")
            live_mode_ack = st.text_input("Type I ACCEPT THE RISK to enable live mode")
            if st.button("Confirm Live Mode"):
                if live_mode_ack == "I ACCEPT THE RISK" and coinbase_client_ready:
                    settings["trading_mode"] = "live"
                    save_settings(storage, control_state, settings)
                    st.rerun()
                elif not coinbase_client_ready:
                    st.error("Coinbase credentials are not ready.")
                else:
                    st.error("Confirmation text did not match.")
        else:
            settings["trading_mode"] = "paper"
            save_settings(storage, control_state, settings)
            st.rerun()

    live_ack = True
    if config.live_enabled:
        st.error("Live cycle requires confirmation.")
        live_ack = st.text_input("Type I ACCEPT THE RISK before running") == "I ACCEPT THE RISK"

    if st.button("Run One Bot Cycle", type="primary", disabled=config.live_enabled and not live_ack):
        with st.spinner("Scoring market and applying bot rules..."):
            st.session_state["last_result"] = run_cycle(config)
            st.rerun()

    new_halted = st.toggle("Emergency halt", value=halted)
    if new_halted != halted:
        state["halted"] = new_halted
        state["halt_reason"] = "Operator emergency halt." if new_halted else None
        storage.save_state(state, state_id)
        st.rerun()

    if st.button("Refresh Dashboard"):
        st.rerun()

cash = float(state.get("cash_usd", 0) or 0)
base = float(state.get("base_size", 0) or 0)
entry_price = state.get("entry_price")
price = 0.0
price_error = None

try:
    price = client.get_spot_price(active_product_id)
except Exception as exc:
    price_error = str(exc)

equity = cash + (base * price)
unrealized_pnl = (base * price) - (base * float(entry_price or price or 0))
realized_pnl = float(state.get("realized_pnl", 0) or 0)
total_fees = float(state.get("total_fees", 0) or 0)
total_pnl = equity - config.starting_cash
daily_loss_used = abs(min(0.0, float(state.get("daily_loss_usd", 0) or 0)))
daily_loss_ratio = min(1.0, daily_loss_used / max(config.max_daily_loss_usd, 0.01))

if price_error:
    st.warning(f"Price fetch failed: {price_error}")

metric_cols = st.columns(6)
metric_cols[0].metric("Estimated Equity", fmt_money(equity), f"{total_pnl:+.2f}")
metric_cols[1].metric("Cash", fmt_money(cash))
metric_cols[2].metric("Position", f"{base:.8f}")
metric_cols[3].metric("Spot", fmt_money(price) if price else "N/A")
metric_cols[4].metric("Realized P/L", fmt_money(realized_pnl))
metric_cols[5].metric("Mode Fees", fmt_money(total_fees))

try:
    candles = client.get_candles(active_product_id)
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
preview = order_preview(signal, state, config)

page = st.sidebar.radio(
    "Navigation",
    ["Home", "Markets", "Trade", "Portfolio", "AI Center", "Activity", "Settings"],
    label_visibility="collapsed",
)

rows = [flatten_event(item) for item in events if (item.get("payload") or {}).get("mode") in {state_id, None}]

if page == "Home":
    st.subheader("Portfolio Home")
    home_left, home_right = st.columns([1.6, 1])
    with home_left:
        render_price_chart(candles, active_product_id)
    with home_right:
        with st.spinner("Building AI recommendation..."):
            watch_rankings = rank_markets(client, config, limit=min(8, len(config.watchlist)))
        top = watch_rankings[0] if watch_rankings else None
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.subheader("AI Recommendation Center")
        if top:
            st.markdown(f'<div class="status-row">{badge(top["action"], action_tone(top["action"]))}{badge(top.get("risk_level", "Risk unknown"), "warn" if top.get("risk_level") == "High" else "neutral")}</div>', unsafe_allow_html=True)
            st.metric("Best Opportunity", top["product_id"])
            st.metric("AI Score", f"{float(top['ai_score']):.2%}")
            st.write(ai_advice(top, config))
            st.caption(top.get("reason", ""))
        else:
            st.info("No AI ranking available yet.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.subheader("What The Bot Will Do")
        if preview:
            st.dataframe(pd.DataFrame([preview]), use_container_width=True, hide_index=True)
        else:
            st.info("The current signal does not meet trade rules.")

    history_frame = equity_history(events, state_id, config.starting_cash)
    if not history_frame.empty:
        st.subheader(f"{state_id.title()} Equity")
        st.line_chart(history_frame.set_index("time"), use_container_width=True, height=220)

elif page == "Markets":
    st.subheader("Markets")
    market_rows = load_market_rows(client)
    search = st.text_input("Search markets", value="")
    left, right = st.columns([1.25, 1])
    with left:
        if not market_rows.empty:
            visible = market_rows.copy()
            if search:
                visible = visible[visible["product_id"].str.contains(search.upper(), na=False)]
            st.dataframe(visible[["product_id", "price", "price_percentage_change_24h", "volume_24h", "status"]].head(120), use_container_width=True, hide_index=True)
        else:
            st.warning("Coinbase market list is unavailable right now.")
    with right:
        scan_all = st.toggle("Scan top USD markets", value=True)
        with st.spinner("AI is scanning markets..."):
            rankings = rank_all_usd_markets(client, config, limit=config.scan_market_limit) if scan_all else rank_markets(client, config, limit=min(12, len(config.watchlist)))
        if rankings:
            ranking_frame = pd.DataFrame(rankings)
            st.dataframe(ranking_frame[["product_id", "action", "confidence", "ai_score", "risk_level", "price", "advice"]], use_container_width=True, hide_index=True)
            top = rankings[0]
            st.write(ai_advice(top, config))
            if st.button(f"Use {top['product_id']} as fixed market"):
                settings["product_id"] = top["product_id"]
                settings["auto_select_market"] = False
                save_settings(storage, control_state, settings)
                st.rerun()
        else:
            st.info("No markets could be ranked.")

elif page == "Trade":
    st.subheader(f"Trade: {active_product_id}")
    left, right = st.columns([2, 1])
    with left:
        render_price_chart(candles, active_product_id)
    with right:
        st.metric("AI Action", signal.action)
        st.metric("Confidence", f"{signal.confidence:.2%}")
        st.write(signal.reason)
        if preview:
            st.subheader("Trade Ticket")
            st.dataframe(pd.DataFrame([preview]), use_container_width=True, hide_index=True)
        else:
            st.info("No eligible trade ticket.")
        st.metric("Entry Price", fmt_money(entry_price) if entry_price else "No open entry")
        st.metric("Unrealized P/L", fmt_money(unrealized_pnl), f"{((price / entry_price - 1) * 100):+.2f}%" if entry_price and price else None)

elif page == "Portfolio":
    st.subheader("Portfolio")
    if coinbase_client_ready:
        if st.button("Sync Coinbase Portfolio", type="primary"):
            st.session_state["coinbase_portfolio"] = coinbase_portfolio_frame(client)
        portfolio = st.session_state.get("coinbase_portfolio", pd.DataFrame())
        if isinstance(portfolio, pd.DataFrame) and not portfolio.empty:
            st.metric("Coinbase Portfolio Value", fmt_money(portfolio["value_usd"].sum()))
            st.dataframe(portfolio, use_container_width=True, hide_index=True)
        else:
            st.info("Click sync to load real Coinbase balances.")
    else:
        st.warning("Coinbase client is not ready. Check Streamlit secrets formatting.")
    st.subheader("Bot State Portfolio")
    st.dataframe(pd.DataFrame([{"mode": state_id, "market": active_product_id, "cash": cash, "base_size": base, "equity": equity, "realized_pnl": realized_pnl}]), use_container_width=True, hide_index=True)

elif page == "AI Center":
    st.subheader("AI Recommendation Center")
    with st.spinner("Scoring market intelligence..."):
        rankings = rank_all_usd_markets(client, config, limit=config.scan_market_limit)
    if rankings:
        top = rankings[0]
        st.markdown(f'<div class="status-row">{badge(top["product_id"], "neutral")}{badge(top["action"], action_tone(top["action"]))}{badge(top.get("risk_level", "Risk unknown"), "warn" if top.get("risk_level") == "High" else "good")}</div>', unsafe_allow_html=True)
        cols = st.columns(4)
        cols[0].metric("Top Market", top["product_id"])
        cols[1].metric("AI Score", f"{float(top['ai_score']):.2%}")
        cols[2].metric("Confidence", f"{float(top['confidence']):.2%}")
        cols[3].metric("Risk", top.get("risk_level", "Unknown"))
        st.write(ai_advice(top, config))
        st.dataframe(pd.DataFrame(rankings)[["product_id", "action", "confidence", "ai_score", "risk_level", "metric_rsi", "metric_macd_hist", "metric_bollinger_width", "advice"]], use_container_width=True, hide_index=True)
    else:
        st.info("No AI rankings available.")

elif page == "Activity":
    st.subheader("Activity Timeline")
    render_trade_cards(rows)
    notifications = [flatten_event(item) for item in events if item.get("kind") in {"notification", "notification_error"}]
    if notifications:
        st.subheader("Notifications")
        st.dataframe(pd.DataFrame(notifications), use_container_width=True, hide_index=True)
    st.subheader("Event History")
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No events logged yet.")
    st.subheader("P/L Heatmap")
    render_heatmap(daily_pnl(events, state_id, config.starting_cash))

elif page == "Settings":
    st.subheader("Risk And Automation Settings")
    risk_cols = st.columns(5)
    risk_cols[0].metric("Daily Loss Used", fmt_money(daily_loss_used))
    risk_cols[1].metric("Daily Loss Limit", fmt_money(config.max_daily_loss_usd))
    risk_cols[2].metric("Trade Cap", fmt_money(config.max_trade_usd))
    risk_cols[3].metric("Fee Model", fmt_pct(config.estimated_fee_pct))
    risk_cols[4].metric("Halt Status", "Halted" if halted else "Active")
    st.progress(daily_loss_ratio, text=f"Daily loss usage: {daily_loss_ratio:.0%}")

    selected_profile = st.selectbox("Strategy profile", list(STRATEGY_PROFILES), index=list(STRATEGY_PROFILES).index(str(settings.get("strategy_profile", "Balanced"))))
    if selected_profile != settings.get("strategy_profile"):
        settings = {**settings, "strategy_profile": selected_profile, **STRATEGY_PROFILES[selected_profile]}
        save_settings(storage, control_state, settings)
        st.rerun()

    with st.form("risk_settings_form"):
        new_product_id = st.text_input("Fixed market", value=str(settings.get("product_id") or config.product_id)).upper()
        new_watchlist = st.text_area("Autonomous watchlist", value=str(settings.get("watchlist") or ",".join(config.watchlist)), height=80)
        new_auto_select = st.toggle("Let bot choose best watchlist market", value=bool(settings.get("auto_select_market", True)))
        new_scan_limit = st.number_input("Top USD markets to scan", min_value=5, max_value=100, value=int(settings.get("scan_market_limit", config.scan_market_limit)), step=5)
        new_max_trade = st.number_input("Max trade USD", min_value=1.0, max_value=100.0, value=float(settings["max_trade_usd"]), step=1.0)
        new_daily_loss = st.number_input("Max daily loss USD", min_value=1.0, max_value=100.0, value=float(settings["max_daily_loss_usd"]), step=1.0)
        new_stop_loss = st.slider("Stop loss", min_value=0.005, max_value=0.20, value=float(settings["stop_loss_pct"]), step=0.005, format="%.3f")
        new_take_profit = st.slider("Take profit", min_value=0.005, max_value=0.30, value=float(settings["take_profit_pct"]), step=0.005, format="%.3f")
        new_buy_conf = st.slider("Buy confidence", min_value=0.40, max_value=0.95, value=float(settings["confidence_to_buy"]), step=0.01)
        new_sell_conf = st.slider("Sell confidence", min_value=0.40, max_value=0.95, value=float(settings["confidence_to_sell"]), step=0.01)
        new_fee = st.slider("Estimated Coinbase fee", min_value=0.0, max_value=0.02, value=float(settings["estimated_fee_pct"]), step=0.001, format="%.3f")
        if st.form_submit_button("Save Runtime Settings", type="primary"):
            settings.update({
                "strategy_profile": selected_profile,
                "product_id": new_product_id,
                "watchlist": ",".join(parse_watchlist(new_watchlist)),
                "auto_select_market": new_auto_select,
                "scan_market_limit": new_scan_limit,
                "max_trade_usd": new_max_trade,
                "max_daily_loss_usd": new_daily_loss,
                "stop_loss_pct": new_stop_loss,
                "take_profit_pct": new_take_profit,
                "confidence_to_buy": new_buy_conf,
                "confidence_to_sell": new_sell_conf,
                "estimated_fee_pct": new_fee,
            })
            save_settings(storage, control_state, settings)
            st.success("Settings saved.")
            st.rerun()

    st.subheader("Paper Account Tools")
    reset_ack = st.text_input("Type RESET PAPER to clear paper state")
    if st.button("Reset Paper Account", disabled=reset_ack != "RESET PAPER"):
        storage.reset_state("paper")
        storage.log_event("paper_reset", {"mode": "paper", "reason": "Operator reset from dashboard."})
        st.rerun()

    st.subheader("Deployment Health")
    health = pd.DataFrame([
        {"item": "Supabase", "status": "Connected" if supabase_connected else "Fallback/local"},
        {"item": "Coinbase API key", "status": "Configured" if config.coinbase_api_key else "Missing"},
        {"item": "Coinbase private key", "status": "Configured" if config.coinbase_api_secret else "Missing"},
        {"item": "Trading mode", "status": config.trading_mode.upper()},
        {"item": "Runner heartbeat", "status": heartbeat_text},
    ])
    st.dataframe(health, use_container_width=True, hide_index=True)
