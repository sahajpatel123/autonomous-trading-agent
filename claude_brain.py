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

SYSTEM_PROMPT = """\
You are a professional prediction market trader specializing in Polymarket.
You have deep expertise in probabilistic reasoning, news analysis, and event forecasting.

You will receive:
1. A list of open prediction markets with current YES/NO prices
2. Your current portfolio state (cash, open positions)
3. Your recent trade history
4. Access to web search for live news and research

PRICES represent probability: a YES price of 0.65 means the market thinks there's a 65% chance of YES.
Look for markets where you believe the true probability is significantly different from the market price.

RETURN FORMAT — respond with ONLY a JSON array. No markdown, no explanation, no preamble.
If you find no good opportunities, return exactly: []

Each element in the array must have this exact shape:
{
  "market_id": "<string>",
  "token_id": "<string — use yes_token_id or no_token_id from the market data>",
  "position": "YES" or "NO",
  "size_usd": <float — USD amount to spend>,
  "confidence_score": <float between 0.0 and 1.0>,
  "reasoning": "<brief explanation of your edge>"
}

TRADING RULES you must follow:
- Only include trades with confidence_score >= 0.7
- size_usd must not exceed $5.00 per trade
- Never allocate more than 30% of available cash to a single trade
- Prefer markets with liquidity_usd > 1000 (more reliable pricing)
- Use web_search to research the underlying event before deciding
- If you have no genuine edge, return []
- Prioritize recency: markets resolving sooner are better for capital velocity\
"""


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
                system=SYSTEM_PROMPT,
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

        if not text_content:
            logger.warning("Claude returned no text content")
            return []

        # Claude should return raw JSON — but defensively strip any markdown fences
        cleaned = text_content
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

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
