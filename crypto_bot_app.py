from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from crypto_bot.bot import run_cycle
from crypto_bot.coinbase_client import CoinbaseClient
from crypto_bot.config import load_config
from crypto_bot.storage import BotStorage
from crypto_bot.strategy import score_market

st.set_page_config(page_title="Crypto Bot Lab", page_icon="₿", layout="wide")

config = load_config(st.secrets)
storage = BotStorage(config)
client = CoinbaseClient(config)
state = storage.load_state()

st.title("Crypto Bot Lab")
st.caption("Autonomous Coinbase trading with paper mode, Supabase logging, and hard risk controls.")

mode_color = "green" if config.trading_mode == "paper" else "red"
st.sidebar.header("Bot Controls")
st.sidebar.markdown(f"**Mode:** :{mode_color}[{config.trading_mode.upper()}]")
st.sidebar.markdown(f"**Market:** `{config.product_id}`")
st.sidebar.markdown(f"**Max trade:** `${config.max_trade_usd:.2f}`")
st.sidebar.markdown(f"**Daily loss stop:** `${config.max_daily_loss_usd:.2f}`")

if st.sidebar.button("Run one bot cycle", type="primary"):
    with st.spinner("Scoring market and executing according to settings..."):
        st.session_state["last_result"] = run_cycle(config)
        st.rerun()

halted = bool(state.get("halted"))
new_halted = st.sidebar.toggle("Emergency halt", value=halted)
if new_halted != halted:
    state["halted"] = new_halted
    storage.save_state(state)
    st.rerun()

cash = float(state.get("cash_usd", 0))
base = float(state.get("base_size", 0))
price = 0.0
try:
    price = client.get_spot_price(config.product_id)
except Exception as exc:
    st.warning(f"Price fetch failed: {exc}")

equity = cash + (base * price)
cols = st.columns(4)
cols[0].metric("Cash", f"${cash:,.2f}")
cols[1].metric("Position", f"{base:.8f}")
cols[2].metric("Spot", f"${price:,.2f}" if price else "N/A")
cols[3].metric("Estimated Equity", f"${equity:,.2f}")

try:
    candles = client.get_candles(config.product_id)
except Exception as exc:
    candles = pd.DataFrame()
    st.error(f"Candle fetch failed: {exc}")

left, right = st.columns([2, 1])
with left:
    st.subheader("Market")
    if not candles.empty:
        chart_data = candles.set_index("time")[["close"]]
        st.line_chart(chart_data)
    else:
        st.info("No candle data available yet.")

with right:
    st.subheader("AI Logic Signal")
    signal = score_market(
        candles,
        has_position=base > 0,
        entry_price=state.get("entry_price"),
        stop_loss_pct=config.stop_loss_pct,
        take_profit_pct=config.take_profit_pct,
    )
    st.metric("Action", signal.action)
    st.metric("Confidence", f"{signal.confidence:.2%}")
    st.write(signal.reason)
    st.json(signal.metrics)

if "last_result" in st.session_state:
    st.subheader("Last Cycle Result")
    st.json(st.session_state["last_result"])

st.subheader("Recent Bot Events")
events = storage.list_events()
if events:
    rows = [
        {
            "created_at": item.get("created_at"),
            "kind": item.get("kind"),
            "action": (item.get("payload") or {}).get("signal", {}).get("action") or (item.get("payload") or {}).get("action"),
            "mode": (item.get("payload") or {}).get("mode"),
            "payload": json.dumps(item.get("payload", {}))[:500],
        }
        for item in events
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.info("No events logged yet.")

with st.expander("Live trading setup"):
    st.markdown(
        """
        To allow live Coinbase orders, add Coinbase CDP Advanced Trade credentials to Streamlit secrets and set `TRADING_MODE = "live"`.
        Keep API permissions narrow, start with small `MAX_TRADE_USD`, and use the emergency halt before changing settings.
        """
    )
