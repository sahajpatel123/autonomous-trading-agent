import os
from dotenv import load_dotenv

load_dotenv()

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Polymarket
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_ADDRESS = os.getenv("POLYMARKET_ADDRESS", "")
CLOB_HOST = os.getenv("CLOB_HOST", "https://clob.polymarket.com")
CHAIN_ID = int(os.getenv("CHAIN_ID", "137"))  # Polygon mainnet

# Trading loop
TRADING_INTERVAL_SECONDS = int(os.getenv("TRADING_INTERVAL_SECONDS", "1800"))  # 30 min
MAX_MARKETS_TO_ANALYZE = int(os.getenv("MAX_MARKETS_TO_ANALYZE", "20"))

# Risk controls
MAX_POSITION_SIZE_USD = float(os.getenv("MAX_POSITION_SIZE_USD", "5.0"))
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "10.0"))
MIN_CONFIDENCE_THRESHOLD = float(os.getenv("MIN_CONFIDENCE_THRESHOLD", "0.7"))
MAX_POSITION_FRACTION = float(os.getenv("MAX_POSITION_FRACTION", "0.30"))  # max 30% of cash per trade

# Persistence
STATE_FILE = os.getenv("STATE_FILE", "state.json")
TRADE_LOG_FILE = os.getenv("TRADE_LOG_FILE", "trades.jsonl")
