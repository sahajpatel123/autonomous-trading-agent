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
        Fetch open prediction markets with current YES/NO prices.
        Returns a list of market dicts ready to send to Claude.
        """
        markets = []
        try:
            response = self._client.get_simplified_markets()
            raw_markets = response.get("data", []) if isinstance(response, dict) else []

            for m in raw_markets[:limit]:
                tokens = m.get("clobTokenIds", [])
                if len(tokens) < 2:
                    continue

                yes_token_id = tokens[0]
                no_token_id = tokens[1]

                yes_price = self._get_price(yes_token_id)
                no_price = self._get_price(no_token_id)

                if yes_price is None or no_price is None:
                    continue

                markets.append({
                    "market_id": m.get("conditionId", m.get("id", "")),
                    "question": m.get("question", ""),
                    "end_date": m.get("endDate", ""),
                    "yes_token_id": yes_token_id,
                    "no_token_id": no_token_id,
                    "yes_price": round(yes_price, 4),
                    "no_price": round(no_price, 4),
                    "volume_usd": float(m.get("volume", 0) or 0),
                    "liquidity_usd": float(m.get("liquidity", 0) or 0),
                    "active": m.get("active", True),
                    "closed": m.get("closed", False),
                })

        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")

        # Filter to only active, non-closed markets
        open_markets = [m for m in markets if m["active"] and not m["closed"]]
        logger.info(f"Fetched {len(open_markets)} open markets")
        return open_markets

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
        """Return current open positions."""
        try:
            raw = self._client.get_positions()
            positions = []
            for p in (raw or []):
                positions.append({
                    "token_id": p.get("token_id", ""),
                    "size_shares": float(p.get("size", 0)),
                    "avg_price": float(p.get("average_entry_price", 0)),
                    "current_value_usd": float(p.get("size", 0)) * float(p.get("average_entry_price", 0)),
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
