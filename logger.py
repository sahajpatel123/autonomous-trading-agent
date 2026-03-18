"""
Trade logger — append-only JSONL file for all agent decisions and executions.
Also configures Python's stdlib logging for console output.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import config


def setup_logging():
    """Configure root logger to write human-readable lines to stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stdout,
    )


class TradeLogger:
    def __init__(self, log_file: str = config.TRADE_LOG_FILE):
        self._path = Path(log_file)

    def _append(self, record: dict):
        record["timestamp"] = datetime.utcnow().isoformat()
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to write trade log: {e}")

    def log_cycle_start(self, portfolio: dict, market_count: int):
        self._append({
            "event": "cycle_start",
            "portfolio": portfolio,
            "markets_fetched": market_count,
        })

    def log_decision(self, decision: dict, approved: bool, reason: str = ""):
        self._append({
            "event": "decision",
            "market_id": decision.get("market_id"),
            "position": decision.get("position"),
            "size_usd": decision.get("size_usd"),
            "confidence_score": decision.get("confidence_score"),
            "reasoning": decision.get("reasoning"),
            "approved": approved,
            "rejection_reason": reason if not approved else "",
        })

    def log_execution(self, decision: dict, result: dict):
        self._append({
            "event": "execution",
            "market_id": decision.get("market_id"),
            "position": decision.get("position"),
            "size_usd": decision.get("size_usd"),
            "order_id": result.get("id", ""),
            "order_status": result.get("status", "unknown"),
            "error": result.get("error", ""),
        })

    def log_error(self, context: str, error: Exception):
        self._append({
            "event": "error",
            "context": context,
            "error": str(error),
            "error_type": type(error).__name__,
        })

    def log_daily_limit_hit(self, daily_loss: float):
        self._append({
            "event": "daily_limit_hit",
            "daily_loss_usd": daily_loss,
            "limit_usd": config.MAX_DAILY_LOSS_USD,
        })

    def log_no_decisions(self):
        self._append({"event": "no_decisions"})
