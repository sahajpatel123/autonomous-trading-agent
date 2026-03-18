"""
Portfolio state manager.
Persists agent state to a JSON file so it survives process restarts.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_DEFAULT_STATE = {
    "cash_usd": 0.0,
    "positions": [],
    "trade_history": [],
    "daily_loss_usd": 0.0,
    "daily_loss_date": "",
    "total_pnl_usd": 0.0,
    "total_trades": 0,
}


class StateManager:
    def __init__(self, state_file: str = config.STATE_FILE):
        self._path = Path(state_file)
        self._state = self._load()

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    data = json.load(f)
                logger.info(f"State loaded from {self._path}")
                # Merge with defaults to handle missing keys after upgrades
                return {**_DEFAULT_STATE, **data}
            except Exception as e:
                logger.error(f"Failed to load state, starting fresh: {e}")
        return dict(_DEFAULT_STATE)

    def save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    # ------------------------------------------------------------------
    # Portfolio accessors
    # ------------------------------------------------------------------

    def get_portfolio(self) -> dict:
        """Return snapshot of current portfolio for Claude context."""
        return {
            "cash_usd": round(self._state["cash_usd"], 4),
            "positions": self._state["positions"],
            "total_pnl_usd": round(self._state["total_pnl_usd"], 4),
            "total_trades": self._state["total_trades"],
        }

    def get_cash(self) -> float:
        return self._state["cash_usd"]

    def set_cash(self, amount: float):
        self._state["cash_usd"] = round(amount, 6)
        self.save()

    def get_positions(self) -> list:
        return self._state["positions"]

    def set_positions(self, positions: list):
        self._state["positions"] = positions
        self.save()

    # ------------------------------------------------------------------
    # Trade history
    # ------------------------------------------------------------------

    def get_trade_history(self, limit: int = 50) -> list:
        return self._state["trade_history"][-limit:]

    def record_trade(self, decision: dict, result: dict):
        """Append a completed trade to history."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "market_id": decision.get("market_id", ""),
            "position": decision.get("position", ""),
            "token_id": decision.get("token_id", ""),
            "size_usd": decision.get("size_usd", 0),
            "confidence_score": decision.get("confidence_score", 0),
            "reasoning": decision.get("reasoning", ""),
            "order_status": result.get("status", "unknown"),
            "order_id": result.get("id", ""),
            "error": result.get("error", ""),
        }
        self._state["trade_history"].append(entry)
        self._state["total_trades"] += 1

        # Deduct from cash if order was placed (not an error)
        if not result.get("error"):
            spent = float(decision.get("size_usd", 0))
            self._state["cash_usd"] = max(0.0, self._state["cash_usd"] - spent)

        # Keep history bounded to last 500 trades
        if len(self._state["trade_history"]) > 500:
            self._state["trade_history"] = self._state["trade_history"][-500:]

        self.save()

    # ------------------------------------------------------------------
    # Daily loss tracking
    # ------------------------------------------------------------------

    def get_daily_loss(self) -> float:
        self._reset_daily_loss_if_new_day()
        return self._state["daily_loss_usd"]

    def add_daily_loss(self, amount: float):
        self._reset_daily_loss_if_new_day()
        self._state["daily_loss_usd"] = round(self._state["daily_loss_usd"] + amount, 6)
        self.save()

    def _reset_daily_loss_if_new_day(self):
        today = date.today().isoformat()
        if self._state["daily_loss_date"] != today:
            self._state["daily_loss_date"] = today
            self._state["daily_loss_usd"] = 0.0
            self.save()
