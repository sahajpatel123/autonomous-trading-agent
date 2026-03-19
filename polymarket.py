"""
Polymarket CLOB API integration.
Handles market fetching, order execution, and portfolio queries.
"""

import logging
import os
from typing import Optional

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import MarketOrderArgs, OrderType, OpenOrderParams, BalanceAllowanceParams, AssetType

import config

logger = logging.getLogger(__name__)

load_dotenv()


class PolymarketClient:
    def __init__(self):
        self._private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "").strip()
        self._address = os.getenv("POLYMARKET_ADDRESS", "").strip()

        if not self._private_key:
            raise ValueError("POLYMARKET_PRIVATE_KEY not set")
        if not self._address:
            raise ValueError("POLYMARKET_ADDRESS not set")

        self._client = ClobClient(
            host="https://clob.polymarket.com",
            key=self._private_key,
            chain_id=POLYGON,
            signature_type=0,
            funder=self._address,
        )
        creds = self._client.create_or_derive_api_creds()
        self._client.set_api_creds(creds)
        logger.info("Polymarket client initialized")

    def get_balance(self):
        try:
            import requests

            # Proxy wallet address where deposited funds are held
            proxy = "0xa90C8AbAB5306401514Bc5573FC4F2422fc1D9Ca"

            # USDC contract on Polygon
            usdc = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

            # eth_call to balanceOf(proxy)
            call_data = "0x70a08231" + "000000000000000000000000" + proxy[2:].lower()

            payload = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": usdc, "data": call_data}, "latest"],
                "id": 1
            }

            r = requests.post(
                "https://polygon-bor-rpc.publicnode.com",
                json=payload,
                timeout=10
            )
            result = r.json().get("result", "0x0")
            balance = int(result, 16) / 1_000_000
            return balance

        except Exception as e:
            print(f"Failed to get balance: {e}")
            return 0.0

    def get_markets(self, limit: int = 20) -> list[dict]:
        """
        Fetch active, high-volume markets from the Gamma API.
        Returns a list of market dicts ready to send to Claude.
        """
        import requests as _requests
        markets = []
        try:
            resp = _requests.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 50,
                    "order": "volume24hr",
                    "ascending": "false",
                },
                timeout=10,
            )
            resp.raise_for_status()
            raw_markets = resp.json()

            for m in raw_markets:
                volume24 = float(m.get("volume24hr") or 0)
                liquidity = float(m.get("liquidity") or 0)
                if volume24 < 100 or liquidity < 500:
                    continue

                # Extract YES/NO token IDs and prices from the tokens list
                tokens = m.get("tokens") or []
                yes_tok = next((t for t in tokens if str(t.get("outcome", "")).upper() == "YES"), None)
                no_tok = next((t for t in tokens if str(t.get("outcome", "")).upper() == "NO"), None)

                # Fall back to outcomePrices array if tokens list is absent
                raw_op = m.get("outcomePrices") or []
                if isinstance(raw_op, str):
                    import json as _json
                    raw_op = _json.loads(raw_op)
                outcome_prices = raw_op
                yes_price = float(yes_tok["price"]) if yes_tok and yes_tok.get("price") is not None \
                    else (float(outcome_prices[0]) if outcome_prices else 0.0)
                no_price = float(no_tok["price"]) if no_tok and no_tok.get("price") is not None \
                    else (float(outcome_prices[1]) if len(outcome_prices) > 1 else round(1 - yes_price, 4))

                yes_token_id = yes_tok["token_id"] if yes_tok and yes_tok.get("token_id") else m.get("conditionId", "")
                no_token_id = no_tok["token_id"] if no_tok and no_tok.get("token_id") else ""

                markets.append({
                    "market_id": m.get("conditionId", ""),
                    "question": m.get("question", ""),
                    "end_date": m.get("endDate", ""),
                    "yes_token_id": yes_token_id,
                    "no_token_id": no_token_id,
                    "yes_price": round(yes_price, 4),
                    "no_price": round(no_price, 4),
                    "liquidity_usd": round(liquidity, 2),
                    "volume_usd": round(float(m.get("volume") or 0), 2),
                    "volume_24hr": round(volume24, 2),
                })

                if len(markets) >= limit:
                    break

        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")

        logger.info(f"Fetched {len(markets)} open markets")
        return markets

    def _get_price(self, token_id: str) -> Optional[float]:
        """Get best buy price for a token (represents probability)."""
        try:
            price = self._client.get_price(token_id, side="BUY")
            return float(price)
        except Exception:
            try:
                midpoint = self._client.get_midpoint(token_id)
                return float(midpoint)
            except Exception:
                return None

    def get_positions(self) -> list[dict]:
        """Return current open positions derived from open orders."""
        from py_clob_client.clob_types import OpenOrderParams
        try:
            raw = self._client.get_orders(OpenOrderParams()) or []
            positions = []
            for p in raw:
                size = float(p.get("size_matched", 0) or p.get("original_size", 0) or 0)
                price = float(p.get("price", 0) or 0)
                positions.append({
                    "token_id": p.get("asset_id", ""),
                    "size_shares": size,
                    "avg_price": price,
                    "current_value_usd": size * price,
                })
            return positions
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def get_trades(self, limit: int = 50) -> list[dict]:
        """Return recent trade history."""
        try:
            raw = self._client.get_trades()
            trades = []
            for t in (raw or [])[:limit]:
                trades.append({
                    "id": t.get("id", ""),
                    "token_id": t.get("token_id", ""),
                    "side": t.get("side", ""),
                    "size": float(t.get("size", 0)),
                    "price": float(t.get("price", 0)),
                    "status": t.get("status", ""),
                    "timestamp": t.get("timestamp", ""),
                })
            return trades
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            return []

    def place_market_order(self, token_id: str, amount_usd: float) -> dict:
        """
        Place a market BUY order (FOK) for the given token.
        amount_usd is the USDC amount to spend.
        Returns order result dict.
        """
        try:
            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=amount_usd,
                side="BUY",
            )
            signed = self._client.create_market_order(order_args)
            result = self._client.post_order(signed, OrderType.FOK)
            logger.info(f"Order placed: token={token_id[:16]}... amount=${amount_usd} result={result}")
            return result or {}
        except Exception as e:
            logger.error(f"Order failed: token={token_id[:16]}... amount=${amount_usd} error={e}")
            return {"error": str(e)}

    def verify_connection(self) -> bool:
        """Health check — returns True if CLOB is reachable."""
        try:
            return self._client.get_ok() is True
        except Exception as e:
            logger.error(f"Connection check failed: {e}")
            return False
