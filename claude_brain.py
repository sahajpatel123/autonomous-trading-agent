"""
Claude API integration — the decision-making brain.
Each call sends full market context + portfolio state + trade history.
Web search tool is enabled so Claude can research live news.
Returns a list of validated trade decision dicts.
"""

import json
import logging
from typing import Any

import anthropic

import config

logger = logging.getLogger(__name__)

def _build_system_prompt() -> str:
    return f"""You are an aggressive prediction market trader managing a $30 portfolio \
on Polymarket. Your job is to find and take the BEST available opportunity \
every cycle — not to find reasons to avoid trading.

For each market provided, assess:
- Is the current market price WRONG based on your knowledge?
- Which direction has the most edge — YES or NO?
- What is your confidence level (0.0 to 1.0)?

Rules:
- Always return your TOP 1-3 best opportunities even if imperfect
- Minimum confidence to include: {config.MIN_CONFIDENCE_THRESHOLD}
- Max position size: $5
- If you have ANY edge above {config.MIN_CONFIDENCE_THRESHOLD} confidence, include it
- Do NOT skip opportunities just because liquidity is imperfect
- Do NOT wait for perfect setups — take the best available

Return ONLY a JSON array:
[{{
  "market_id": str,
  "token_id": "<use yes_token_id or no_token_id from the market data>",
  "position": "YES" or "NO",
  "size_usd": float (max 5.0),
  "confidence_score": float,
  "reasoning": str (one sentence)
}}]

If truly zero opportunities exist, return [].
Otherwise always return at least one trade."""


class ClaudeBrain:
    def __init__(self):
        if not config.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def get_trade_decisions(
        self,
        markets: list[dict],
        portfolio: dict,
        trade_history: list[dict],
    ) -> list[dict]:
        """
        Ask Claude to analyse markets and return trade decisions.
        Returns a (possibly empty) list of decision dicts.
        """
        if not markets:
            logger.warning("No markets to analyse — skipping Claude call")
            return []

        user_message = self._build_user_message(markets, portfolio, trade_history)

        try:
            response = self._client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=4096,
                system=_build_system_prompt(),
                tools=[
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 5,
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            )
            return self._parse_response(response)
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error calling Claude: {e}")
            return []

    def _build_user_message(
        self,
        markets: list[dict],
        portfolio: dict,
        trade_history: list[dict],
    ) -> str:
        payload: dict[str, Any] = {
            "portfolio": portfolio,
            "recent_trades": trade_history[-20:],  # last 20 trades for context
            "open_markets": markets,
        }
        return (
            "Here is your current context. Analyse the markets, research with web search "
            "where needed, and return your trade decisions as a JSON array.\n\n"
            + json.dumps(payload, indent=2, default=str)
        )

    def _parse_response(self, response) -> list[dict]:
        """Extract and validate the JSON array from Claude's response."""
        # Find the last text block in the response (after any tool use turns)
        text_content = ""
        for block in reversed(response.content):
            if hasattr(block, "text"):
                text_content = block.text.strip()
                break

        logger.info(f"Claude raw response: {text_content}")

        if not text_content:
            logger.warning("Claude returned no text content")
            return []

        # Extract the JSON array by finding the outermost [ ... ]
        start = text_content.find("[")
        end = text_content.rfind("]")
        if start == -1 or end == -1 or end < start:
            logger.error(f"No JSON array found in Claude response:\n{text_content[:500]}")
            return []
        cleaned = text_content[start:end + 1]

        try:
            decisions = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude JSON: {e}\nRaw response:\n{text_content[:500]}")
            return []

        if not isinstance(decisions, list):
            logger.error(f"Claude returned non-list JSON: {type(decisions)}")
            return []

        valid = []
        for d in decisions:
            if not isinstance(d, dict):
                continue
            # Ensure required fields are present
            required = {"market_id", "token_id", "position", "size_usd", "confidence_score"}
            if not required.issubset(d.keys()):
                logger.warning(f"Decision missing required fields: {d}")
                continue
            valid.append(d)

        logger.info(f"Claude returned {len(valid)} valid decision(s)")
        return valid
