from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import BotConfig

DATA_DIR = Path("data/crypto_bot")
STATE_FILE = DATA_DIR / "state.json"
EVENTS_FILE = DATA_DIR / "events.json"
STATE_IDS = {"paper": DATA_DIR / "paper_state.json", "live": DATA_DIR / "live_state.json", "control": DATA_DIR / "control_state.json"}


DEFAULT_STATE = {
    "cash_usd": 100.0,
    "base_size": 0.0,
    "entry_price": None,
    "realized_pnl": 0.0,
    "total_fees": 0.0,
    "daily_loss_usd": 0.0,
    "daily_loss_date": None,
    "last_cycle_at": None,
    "last_action": None,
    "last_error": None,
    "halted": False,
    "updated_at": None,
}

DEFAULT_CONTROL_STATE = {
    "settings": {},
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

    def load_state(self, state_id: str = "paper") -> dict[str, Any]:
        defaults = self._defaults_for(state_id)
        if self._supabase:
            try:
                rows = self._supabase.table("crypto_bot_state").select("*").eq("id", state_id).execute().data
                if rows:
                    return {**defaults, **rows[0].get("payload", {})}
            except Exception:
                pass
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = self._state_path(state_id)
        if not path.exists():
            state = deepcopy(defaults)
            if state_id in {"paper", "live"}:
                state["cash_usd"] = self.config.starting_cash
            self.save_state(state, state_id)
            return state
        return {**defaults, **json.loads(path.read_text(encoding="utf-8"))}

    def save_state(self, state: dict[str, Any], state_id: str = "paper") -> None:
        state = {**state, "updated_at": now_iso()}
        if self._supabase:
            try:
                self._supabase.table("crypto_bot_state").upsert({"id": state_id, "payload": state}).execute()
                return
            except Exception:
                pass
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._state_path(state_id).write_text(json.dumps(state, indent=2), encoding="utf-8")

    def reset_state(self, state_id: str = "paper") -> dict[str, Any]:
        state = deepcopy(self._defaults_for(state_id))
        if state_id in {"paper", "live"}:
            state["cash_usd"] = self.config.starting_cash
        self.save_state(state, state_id)
        return state

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

    def list_events(self, limit: int = 250) -> list[dict[str, Any]]:
        if self._supabase:
            try:
                return self._supabase.table("crypto_bot_events").select("*").order("created_at", desc=True).limit(limit).execute().data
            except Exception:
                pass
        if not EVENTS_FILE.exists():
            return []
        return list(reversed(json.loads(EVENTS_FILE.read_text(encoding="utf-8"))[-limit:]))

    def _state_path(self, state_id: str) -> Path:
        if state_id == "default":
            return STATE_FILE
        return STATE_IDS.get(state_id, DATA_DIR / f"{state_id}_state.json")

    def _defaults_for(self, state_id: str) -> dict[str, Any]:
        if state_id == "control":
            return deepcopy(DEFAULT_CONTROL_STATE)
        return deepcopy(DEFAULT_STATE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
