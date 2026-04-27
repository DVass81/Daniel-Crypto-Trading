# Crypto Bot Lab

A Streamlit, Supabase, and Coinbase Advanced Trade experiment for autonomous crypto trading.

This bot is intentionally built with paper mode first, risk limits, persistent logging, and an emergency halt. It can place live Coinbase orders only when `TRADING_MODE = "live"` is set and Coinbase API credentials are configured.

No trading bot can guarantee turning $100 into $1,000 in 30 days. Treat live mode as a high-risk experiment.

## Run Locally

```bash
pip install -r requirements.txt
streamlit run crypto_bot_app.py
```

## Background Runner

```bash
python crypto_bot_runner.py
```

## Streamlit Secrets

Start in paper mode:

```toml
TRADING_MODE = "paper"
PRODUCT_ID = "BTC-USD"
STARTING_CASH = "100"
MAX_TRADE_USD = "15"
MAX_DAILY_LOSS_USD = "15"
ESTIMATED_FEE_PCT = "0.006"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "your-anon-key"
```

Only add live trading credentials when you are ready to risk real money:

```toml
COINBASE_API_KEY = "organizations/{org_id}/apiKeys/{key_id}"
COINBASE_API_SECRET = "-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
TRADING_MODE = "live"
```

## Supabase

Run `supabase_crypto_schema.sql` in the Supabase SQL editor.

## Streamlit Cloud

Deploy this repo with:

- Main file path: `crypto_bot_app.py`
- Python requirements: `requirements.txt`
- Secrets: the values above

## Operations

The Streamlit app is the control dashboard. For true always-on operation, run `python crypto_bot_runner.py` on a small always-on host such as Render, Railway, Fly.io, or a VPS. The dashboard shows the runner heartbeat from the active paper/live state.

Paper and live trading keep separate state records, so paper testing does not overwrite live state. The dashboard can switch modes, but live mode requires explicit confirmation text and Coinbase credentials.
