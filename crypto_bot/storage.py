from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import BotConfig

DATA_DIR = Path("data/crypto_bot")
STATE_FILE = DATA_DIR / "state.json"
EVENTS_FILE = DATA_DIR / "events.json"


DEFAULT_STATE = {
    "cash_usd": 100.0,
    "base_size": 0.0,
    "entry_price": None,
    "realized_pnl": 0.0,
    "total_fees": 0.0,
    "daily_loss_usd": 0.0,
    "halted": False,
    "updated_at": None,
}


class BotStorage:
    def __init__(self, config: BotConfig):
        self.config = config
        self._supabase = None
        if config.supabase_url and config.supabase_anon_key:
            try:
                from supabase import create_client

                self._supabase = create_client(config.supabase_url, config.supabase_anon_key)
            except Exception:
                self._supabase = None

    def load_state(self) -> dict[str, Any]:
        if self._supabase:
            try:
                rows = self._supabase.table("crypto_bot_state").select("*").eq("id", "default").execute().data
                if rows:
                    return {**DEFAULT_STATE, **rows[0].get("payload", {})}
            except Exception:
                pass
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not STATE_FILE.exists():
            state = {**DEFAULT_STATE, "cash_usd": self.config.starting_cash}
            self.save_state(state)
            return state
        return {**DEFAULT_STATE, **json.loads(STATE_FILE.read_text(encoding="utf-8"))}

    def save_state(self, state: dict[str, Any]) -> None:
        state = {**state, "updated_at": now_iso()}
        if self._supabase:
            try:
                self._supabase.table("crypto_bot_state").upsert({"id": "default", "payload": state}).execute()
                return
            except Exception:
                pass
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def log_event(self, kind: str, payload: dict[str, Any]) -> None:
        event = {"created_at": now_iso(), "kind": kind, "payload": payload}
        if self._supabase:
            try:
                self._supabase.table("crypto_bot_events").insert(event).execute()
                return
            except Exception:
                pass
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        events = []
        if EVENTS_FILE.exists():
            events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
        events.append(event)
        EVENTS_FILE.write_text(json.dumps(events[-500:], indent=2), encoding="utf-8")

    def list_events(self) -> list[dict[str, Any]]:
        if self._supabase:
            try:
                return self._supabase.table("crypto_bot_events").select("*").order("created_at", desc=True).limit(100).execute().data
            except Exception:
                pass
        if not EVENTS_FILE.exists():
            return []
        return list(reversed(json.loads(EVENTS_FILE.read_text(encoding="utf-8"))[-100:]))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
