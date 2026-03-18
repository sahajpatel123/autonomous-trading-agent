# SKILL.md — Autonomous Trading Agent

Architecture reference for future Claude Code sessions on this project.

---

## What This Project Does

A fully autonomous Python agent that trades on [Polymarket](https://polymarket.com) prediction markets 24/7.
Claude API (`claude-sonnet-4-20250514`) acts as the decision-making brain, using web search to research live news before placing trades.
No human intervention once deployed. Runs on Railway.

---

## Module Map

| File | Responsibility |
|------|----------------|
| `agent.py` | Infinite loop — orchestrates all modules |
| `polymarket.py` | Polymarket CLOB API wrapper (markets, orders, positions) |
| `claude_brain.py` | Claude API call with web_search tool; parses JSON decisions |
| `risk.py` | Pre-execution validation (confidence, size caps, daily loss) |
| `state.py` | JSON-file persistence of portfolio + trade history |
| `logger.py` | Append-only JSONL trade log + stdlib logging setup |
| `config.py` | All settings from env vars with defaults |

---

## Data Flow (one loop cycle)

```
polymarket.get_markets(20)      → list[MarketDict]
polymarket.get_balance()        → float (USDC)
polymarket.get_positions()      → list[PositionDict]
state.get_trade_history(50)     → list[TradeDict]
        ↓
claude_brain.get_trade_decisions(markets, portfolio, history)
    → Claude uses web_search up to 5× for live research
    → Returns list[DecisionDict] | []
        ↓
for each decision:
    risk.check_trade(decision, portfolio, daily_loss) → (bool, reason)
    if approved:
        polymarket.place_market_order(token_id, size_usd)  # FOK market order
        state.record_trade(decision, result)
        state.add_daily_loss(size_usd)
        ↓
time.sleep(TRADING_INTERVAL_SECONDS)
```

---

## Key Data Shapes

### MarketDict (what Claude sees)
```python
{
    "market_id": str,           # conditionId hex
    "question": str,            # e.g. "Will X happen by Y?"
    "end_date": str,            # ISO date
    "yes_token_id": str,        # 256-bit int as string
    "no_token_id": str,
    "yes_price": float,         # 0–1 (= probability)
    "no_price": float,
    "volume_usd": float,
    "liquidity_usd": float,
}
```

### DecisionDict (Claude's output)
```python
{
    "market_id": str,
    "token_id": str,            # yes_token_id or no_token_id
    "position": "YES" | "NO",
    "size_usd": float,          # USD to spend
    "confidence_score": float,  # 0–1
    "reasoning": str,
}
```

### state.json schema
```json
{
  "cash_usd": 24.0,
  "positions": [],
  "trade_history": [],
  "daily_loss_usd": 0.0,
  "daily_loss_date": "2026-03-18",
  "total_pnl_usd": 0.0,
  "total_trades": 0
}
```

---

## Risk Rules (all env-configurable)

| Rule | Default | Env var |
|------|---------|---------|
| Min confidence to trade | 0.70 | `MIN_CONFIDENCE_THRESHOLD` |
| Max USD per trade | $5.00 | `MAX_POSITION_SIZE_USD` |
| Max % of cash per trade | 30% | `MAX_POSITION_FRACTION` |
| Daily loss limit | $10.00 | `MAX_DAILY_LOSS_USD` |
| Loop interval | 1800s | `TRADING_INTERVAL_SECONDS` |

---

## Polymarket Auth

Uses `py-clob-client` with **EOA signature_type=0** (standard Polygon wallet).
API credentials are derived deterministically from the private key via `create_or_derive_api_creds()` — no separate credential storage needed.

Relevant env vars:
- `POLYMARKET_PRIVATE_KEY` — hex private key (`0x...`)
- `POLYMARKET_ADDRESS` — corresponding public address

---

## Claude API Call

```python
client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    system=SYSTEM_PROMPT,
    tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
    messages=[{"role": "user", "content": <json payload>}],
)
```

Claude must return **only a raw JSON array** — no markdown fences, no prose.
`_parse_response()` in `claude_brain.py` defensively strips markdown if present.

---

## Deployment (Railway)

1. Push this repo to GitHub
2. Create new Railway project → Deploy from GitHub repo
3. Add all env vars from `.env.example` in Railway dashboard
4. Railway uses `railway.json` → runs `python agent.py` as a worker
5. `restartPolicyType: ON_FAILURE` ensures auto-restart on crash

Logs: `railway logs --tail`

---

## Common Debugging Commands

```bash
# Check last 20 trade decisions
tail -20 trades.jsonl | python3 -m json.tool

# Check current portfolio state
cat state.json | python3 -m json.tool

# Verify Polymarket connection
python3 -c "from polymarket import PolymarketClient; c = PolymarketClient(); print(c.get_balance())"

# Verify Claude returns valid JSON
python3 -c "
from claude_brain import ClaudeBrain
b = ClaudeBrain()
print(b.get_trade_decisions([], {'cash_usd': 24}, []))
"

# Run one cycle manually
python3 agent.py
```

---

## Known Limitations / Future Work

- `state.json` lives on ephemeral Railway disk — lost on redeploy. Consider Railway volume mount or SQLite for persistence.
- Daily loss tracking is conservative: counts full `size_usd` as loss even if order partially fills.
- No position closing logic yet — agent only opens positions. Add sell logic to `polymarket.py` once initial trading is validated.
- `get_positions()` is an undocumented Polymarket endpoint — may change. Treat as best-effort.
