"""
Risk management — validates every Claude decision before execution.
All limits are loaded from config so they can be tuned via env vars.
"""

import logging

import config

logger = logging.getLogger(__name__)


class RiskManager:
    def check_trade(
        self,
        decision: dict,
        portfolio: dict,
        daily_loss_usd: float,
    ) -> tuple[bool, str]:
        """
        Validate a Claude trade decision against all risk rules.
        Returns (approved: bool, reason: str).
        """
        confidence = decision.get("confidence_score", 0)
        size_usd = decision.get("size_usd", 0)
        cash = portfolio.get("cash_usd", 0)

        # 1. Confidence threshold
        if confidence < config.MIN_CONFIDENCE_THRESHOLD:
            reason = f"Confidence {confidence:.2f} below threshold {config.MIN_CONFIDENCE_THRESHOLD}"
            logger.info(f"Trade rejected: {reason}")
            return False, reason

        # 2. Size sanity
        if size_usd <= 0:
            reason = "size_usd must be positive"
            logger.info(f"Trade rejected: {reason}")
            return False, reason

        # 3. Max position size cap
        if size_usd > config.MAX_POSITION_SIZE_USD:
            reason = f"size_usd ${size_usd} exceeds MAX_POSITION_SIZE_USD ${config.MAX_POSITION_SIZE_USD}"
            logger.info(f"Trade rejected: {reason}")
            return False, reason

        # 4. Max fraction of remaining cash
        max_from_cash = cash * config.MAX_POSITION_FRACTION
        if size_usd > max_from_cash:
            reason = (
                f"size_usd ${size_usd:.2f} exceeds {config.MAX_POSITION_FRACTION*100:.0f}% "
                f"of cash ${cash:.2f} (max ${max_from_cash:.2f})"
            )
            logger.info(f"Trade rejected: {reason}")
            return False, reason

        # 5. Sufficient cash
        if size_usd > cash:
            reason = f"Insufficient cash: need ${size_usd:.2f}, have ${cash:.2f}"
            logger.info(f"Trade rejected: {reason}")
            return False, reason

        # 5b. Cash floor — never let balance drop below dead floor
        if cash - size_usd < config.MIN_CASH_FLOOR:
            reason = (
                f"Trade would reduce cash to ${cash - size_usd:.2f}, "
                f"below MIN_CASH_FLOOR ${config.MIN_CASH_FLOOR}"
            )
            logger.info(f"Trade rejected: {reason}")
            return False, reason

        # 6. Daily loss limit
        if self.is_daily_limit_breached(daily_loss_usd):
            reason = (
                f"Daily loss ${daily_loss_usd:.2f} already at/exceeds limit "
                f"${config.MAX_DAILY_LOSS_USD}"
            )
            logger.info(f"Trade rejected: {reason}")
            return False, reason

        # 7. Required fields present
        if decision.get("position") not in ("YES", "NO"):
            reason = f"Invalid position value: {decision.get('position')}"
            logger.info(f"Trade rejected: {reason}")
            return False, reason

        return True, ""

    def is_daily_limit_breached(self, daily_loss_usd: float) -> bool:
        return daily_loss_usd >= config.MAX_DAILY_LOSS_USD

    def clamp_size(self, requested_usd: float, cash_usd: float) -> float:
        """Clamp a requested size to safe bounds (useful if Claude slightly overshoots)."""
        max_allowed = min(
            config.MAX_POSITION_SIZE_USD,
            cash_usd * config.MAX_POSITION_FRACTION,
            cash_usd,
        )
        return round(min(requested_usd, max_allowed), 2)
