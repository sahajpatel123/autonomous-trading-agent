# Autonomous Trading Agent

A fully autonomous Python agent that trades on [Polymarket](https://polymarket.com) prediction markets 24/7.
Claude API acts as the decision-making brain — fetching live news and reasoning about event outcomes to identify mispriced markets.

---

## Architecture

```
agent.py (infinite loop)
  ├── polymarket.py   — Fetch markets, place orders, query portfolio
  ├── claude_brain.py — Ask Claude for trade decisions (web search enabled)
  ├── risk.py         — Validate each decision before execution
  ├── state.py        — Persist portfolio state across restarts
  ├── logger.py       — Append-only JSONL trade log
  └── config.py       — All settings from environment variables
```

Per-cycle flow:
1. Fetch ~20 open Polymarket markets with current YES/NO prices
2. Sync balance + positions from chain
3. Send markets + portfolio + trade history to Claude (with web search)
4. Claude returns a JSON array of trade decisions
5. Risk-check each decision, execute approved ones as market orders
6. Sleep, repeat

---

## Prerequisites

- Python 3.11+
- A [Polygon](https://polygon.technology/) wallet with USDC on Polygon mainnet
- [Anthropic API key](https://console.anthropic.com/)
- Polymarket account linked to your wallet (for USDC allowance approval)

---

## Local Setup

```bash
# 1. Clone and install dependencies
git clone <repo-url>
cd autonomous-trading-agent
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env and fill in your API keys

# 3. Run
python agent.py
```

The agent logs to stdout. Trade decisions and executions are also written to `trades.jsonl`.
Portfolio state persists in `state.json` — the agent picks up where it left off on restart.

---

## Environment Variables

See `.env.example` for all options with descriptions and defaults.

Required:
| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `POLYMARKET_PRIVATE_KEY` | Hex private key of your Polygon wallet (`0x...`) |
| `POLYMARKET_ADDRESS` | Public address corresponding to above key |

Key risk controls (all have sensible defaults):
| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_POSITION_SIZE_USD` | `5.0` | Max USD per single trade |
| `MAX_DAILY_LOSS_USD` | `10.0` | Stop trading for the day after this loss |
| `MIN_CONFIDENCE_THRESHOLD` | `0.7` | Claude must exceed this to execute |
| `TRADING_INTERVAL_SECONDS` | `1800` | Loop interval (30 min default) |

---

## Deploying to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
3. Select this repository
4. Add environment variables in the Railway dashboard (from your `.env`)
5. Railway reads `railway.json` and runs `python agent.py` as a persistent worker
6. Enable auto-restart: already configured in `railway.json` (`restartPolicyType: ON_FAILURE`)

View live logs:
```bash
railway logs --tail
```

> **Note on persistence:** Railway's default disk is ephemeral — `state.json` and `trades.jsonl` are lost on redeploy. For long-running production use, attach a Railway Volume and set `STATE_FILE` and `TRADE_LOG_FILE` to paths on that volume.

---

## Deploying to Render

1. Create a new **Background Worker** service
2. Connect your GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `python agent.py`
5. Add environment variables in Render dashboard
6. Enable "Auto-Deploy" and "Restart on Failure"

---

## Monitoring

```bash
# Live decisions (last 20)
tail -f trades.jsonl | python3 -c "import sys,json; [print(json.dumps(json.loads(l), indent=2)) for l in sys.stdin]"

# Current portfolio
cat state.json | python3 -m json.tool

# Count trades by event type
grep -o '"event":"[^"]*"' trades.jsonl | sort | uniq -c
```

---

## Safety Notes

- This agent spends real money autonomously. Start with the lowest comfortable capital.
- The daily loss limit (`MAX_DAILY_LOSS_USD`) is your main safety net — keep it low.
- All Polymarket orders are **market orders (FOK)**: they execute immediately at current prices or not at all.
- Claude's reasoning is logged in `trades.jsonl` — review it regularly to understand why trades were made.
- The agent will not trade if confidence is below `MIN_CONFIDENCE_THRESHOLD`. Raise this to 0.8–0.9 for more conservative operation.
