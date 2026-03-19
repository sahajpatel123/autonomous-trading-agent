"""
Autonomous trading agent — main entry point.
Runs an infinite loop: fetch markets → ask Claude → execute trades → sleep.
Never exits on its own; Railway/Render restart handles crashes.
"""

import logging
import time
from datetime import datetime, timezone

import config
from claude_brain import ClaudeBrain
from logger import TradeLogger, setup_logging
from polymarket import PolymarketClient
from risk import RiskManager
from state import StateManager

setup_logging()
logger = logging.getLogger(__name__)


def run():
    logger.info("=== Autonomous Trading Agent starting ===")
    logger.info(
        f"Config: interval={config.TRADING_INTERVAL_SECONDS}s "
        f"max_position=${config.MAX_POSITION_SIZE_USD} "
        f"max_daily_loss=${config.MAX_DAILY_LOSS_USD} "
        f"min_confidence={config.MIN_CONFIDENCE_THRESHOLD}"
    )

    polymarket = PolymarketClient()
    brain = ClaudeBrain()
    risk = RiskManager()
    state = StateManager()
    trade_logger = TradeLogger()

    # Sync initial cash balance from chain
    on_chain_balance = polymarket.get_balance()
    if on_chain_balance > 0 and state.get_cash() == 0.0:
        logger.info(f"Initialising cash from chain balance: ${on_chain_balance:.2f}")
        state.set_cash(on_chain_balance)

    cycle = 0
    while True:
        cycle += 1
        cycle_start = datetime.now(timezone.utc).isoformat()
        logger.info(f"--- Cycle {cycle} starting at {cycle_start} ---")

        try:
            _run_cycle(polymarket, brain, risk, state, trade_logger)
        except Exception as e:
            logger.exception(f"Unhandled error in cycle {cycle}: {e}")
            trade_logger.log_error("main_loop", e)
            # Brief pause before retrying on unexpected errors
            time.sleep(60)
            continue

        logger.info(f"Cycle {cycle} complete. Sleeping {config.TRADING_INTERVAL_SECONDS}s …")
        time.sleep(config.TRADING_INTERVAL_SECONDS)


def _run_cycle(
    polymarket: PolymarketClient,
    brain: ClaudeBrain,
    risk: RiskManager,
    state: StateManager,
    trade_logger: TradeLogger,
):
    # ------------------------------------------------------------------ #
    # 1. Daily loss guard
    # ------------------------------------------------------------------ #
    daily_loss = state.get_daily_loss()
    if risk.is_daily_limit_breached(daily_loss):
        logger.warning(
            f"Daily loss limit reached (${daily_loss:.2f} >= ${config.MAX_DAILY_LOSS_USD}). "
            "Skipping this cycle."
        )
        trade_logger.log_daily_limit_hit(daily_loss)
        return

    # ------------------------------------------------------------------ #
    # 2. Fetch live data
    # ------------------------------------------------------------------ #
    markets = polymarket.get_markets(limit=config.MAX_MARKETS_TO_ANALYZE)
    if not markets:
        logger.warning("No markets returned — skipping Claude call this cycle")
        return

    # Sync cash + positions from chain so Claude sees accurate state
    on_chain_balance = polymarket.get_balance()
    if on_chain_balance > 0:
        state.set_cash(on_chain_balance)

    on_chain_positions = polymarket.get_positions()
    if on_chain_positions is not None:
        state.set_positions(on_chain_positions)

    portfolio = state.get_portfolio()
    trade_history = state.get_trade_history(limit=50)

    trade_logger.log_cycle_start(portfolio, len(markets))
    logger.info(
        f"Portfolio: cash=${portfolio['cash_usd']:.2f}, "
        f"positions={len(portfolio['positions'])}, "
        f"markets={len(markets)}"
    )

    # ------------------------------------------------------------------ #
    # 3. Ask Claude for decisions
    # ------------------------------------------------------------------ #
    decisions = brain.get_trade_decisions(markets, portfolio, trade_history)

    if not decisions:
        logger.info("Claude found no trade opportunities this cycle")
        trade_logger.log_no_decisions()
        return

    # ------------------------------------------------------------------ #
    # 4. Risk-check and execute each decision
    # ------------------------------------------------------------------ #
    executed = 0
    for decision in decisions:
        # Re-read portfolio state before each trade (cash changes with each order)
        portfolio = state.get_portfolio()
        daily_loss = state.get_daily_loss()

        approved, reason = risk.check_trade(decision, portfolio, daily_loss)
        trade_logger.log_decision(decision, approved, reason)

        if not approved:
            continue

        # Resolve token_id from market data based on position direction
        market_lookup = {m["market_id"]: m for m in markets}
        market = market_lookup.get(decision["market_id"], {})
        if decision.get("position", "YES").upper() == "YES":
            token_id = market.get("yes_token_id", "")
        else:
            token_id = market.get("no_token_id", "")

        if not token_id:
            logger.error(f"Could not resolve token_id for market {decision['market_id']}")
            continue

        # Place the order
        result = polymarket.place_market_order(
            token_id=token_id,
            amount_usd=decision["size_usd"],
        )
        trade_logger.log_execution(decision, result)
        state.record_trade(decision, result)

        if result.get("error"):
            logger.error(f"Order failed: {result['error']}")
        else:
            executed += 1
            # Track loss conservatively: every dollar spent could be lost
            state.add_daily_loss(decision["size_usd"])
            logger.info(
                f"Executed: {decision['position']} ${decision['size_usd']:.2f} "
                f"on market {decision['market_id'][:16]}… "
                f"(confidence={decision['confidence_score']:.2f})"
            )

    logger.info(f"Cycle complete: {executed}/{len(decisions)} decisions executed")


if __name__ == "__main__":
    run()
