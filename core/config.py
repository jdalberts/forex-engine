"""Central configuration — loaded once from .env."""

from __future__ import annotations

import os
from datetime import time as dtime

from dotenv import load_dotenv

load_dotenv()

# ── Broker selection ──────────────────────────────────────────────────────────
# Set BROKER=mt5 in .env to use MetaTrader 5 (via Pepperstone/IC Markets).
# Set BROKER=ig  (or omit) to keep using IG Markets.
BROKER: str = os.environ.get("BROKER", "ig").lower()

# ── IG credentials (only required when BROKER=ig) ────────────────────────────
IG_API_KEY: str     = os.environ.get("IG_API_KEY", "")
IG_IDENTIFIER: str  = os.environ.get("IG_IDENTIFIER", "")
IG_PASSWORD: str    = os.environ.get("IG_PASSWORD", "")
IG_ACCOUNT_ID: str  = os.environ.get("IG_ACCOUNT_ID", "Z69JGB")
IG_DEMO: bool       = os.environ.get("IG_DEMO", "true").lower() == "true"

# ── MT5 credentials (only required when BROKER=mt5) ──────────────────────────
# No API key needed — MT5 uses your broker account login + password.
# Get these from your Pepperstone/IC Markets account after installing MT5.
MT5_LOGIN: int      = int(os.environ.get("MT5_LOGIN", "0"))
MT5_PASSWORD: str   = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER: str     = os.environ.get("MT5_SERVER", "")       # e.g. "Pepperstone-Demo" or "ICMarketsSC-Demo"
MT5_PATH: str       = os.environ.get("MT5_PATH", "")         # path to terminal64.exe (optional)

# ── Instruments ───────────────────────────────────────────────────────────────
# All share the London/NY overlap window (14:00–18:00 SAST)
# pip_value_usd: USD value per pip per 1 standard contract (100,000 base units)
#   EUR/USD: 100,000 × 0.0001 = $10
#   GBP/USD: 100,000 × 0.0001 = $10 (GBP quoted in USD)
#   USD/CHF: 100,000 × 0.0001 = CHF10 → ~$12.50 at 0.80 USDCHF
#   GBP/JPY: 100,000 × 0.01   = JPY1000 → ~$6.30 at 158 USDJPY
PAIRS: dict = {
    # epic:        IG instrument ID (used when BROKER=ig)
    # mt5_symbol:  MT5 symbol name  (used when BROKER=mt5)
    # price_scale: divide raw IG price by this (MT5 always returns readable prices, uses 1)
    # EURUSD removed — unprofitable across all 256 parameter combos on 50k bars (best: -8.4%)
    "GBPUSD": {"epic": "CS.D.GBPUSD.CFD.IP", "mt5_symbol": "GBPUSD", "currency": "USD", "pip_size": 0.0001, "pip_value_usd": 10.0,  "price_scale": 1, "max_spread_pips": 2.0},
    "USDCHF": {"epic": "CS.D.USDCHF.CFD.IP", "mt5_symbol": "USDCHF", "currency": "CHF", "pip_size": 0.0001, "pip_value_usd": 12.5,  "price_scale": 1, "max_spread_pips": 2.0},
    "GBPJPY": {"epic": "CS.D.GBPJPY.CFD.IP", "mt5_symbol": "GBPJPY", "currency": "JPY", "pip_size": 0.01,   "pip_value_usd":  6.3,  "price_scale": 1, "max_spread_pips": 3.0},
    # Commodity CFDs — Pepperstone MT5 (continuous, no rollover)
    "XAUUSD": {"epic": "CS.D.CFEGOLD.CFE.IP", "mt5_symbol": "XAUUSD", "currency": "USD", "pip_size": 0.10,   "pip_value_usd": 10.0,  "price_scale": 1, "max_spread_pips": 5.0},
    "SPOTCRUDE": {"epic": "CS.D.OILCRUD.CFE.IP", "mt5_symbol": "SpotCrude", "currency": "USD", "pip_size": 0.01, "pip_value_usd": 1.0, "price_scale": 1, "max_spread_pips": 5.0},
}

# ── Session window (UTC) ──────────────────────────────────────────────────────
# London/NY overlap = 12:00–16:00 UTC = 14:00–18:00 SAST
SESSION_START_UTC = dtime(12, 0)
SESSION_END_UTC   = dtime(16, 0)

# ── Risk ──────────────────────────────────────────────────────────────────────
INITIAL_BALANCE: float   = 20_000.0
RISK_PER_TRADE: float    = 0.01    # [UPDATED — Step 5] 1 % of account per trade (was 0.5 %)
SOFT_DRAWDOWN: float     = 0.04    # 4 % → scale risk down to 25 %  [was 0.02 — 2% triggered too easily on normal variance; 4% is standard]
HARD_DRAWDOWN: float     = 0.08    # 8 % → halt trading entirely    [was 0.04 — 4% halt was very aggressive; 8% is industry standard]
MAX_SPREAD_PIPS: float   = 2.0     # reject if spread wider than 2 pips
DAILY_LOSS_LIMIT: float  = 0.03    # [NEW — Step 5] pause if today's loss exceeds 3 % of balance
TRAILING_ATR_MULT: float = 2.0     # trailing stop distance in ATR units [optim2: was 1.5 → 2.0 let winners breathe]

# ── Data ──────────────────────────────────────────────────────────────────────
DB_PATH: str        = os.environ.get("DB_PATH", "data/forex_engine.db")
DB_PRUNE_DAYS: int  = 90           # [NEW — Step 9] delete quotes older than this many days
HISTORY_BARS: int   = 1000         # bars to seed on first run  [was 500 — 500×1h = ~21 days; 1000 = ~42 days, better regime warm-up]
QUOTE_INTERVAL_SEC  = 15           # live quote polling interval (4 pairs × 4/min = safe)
LOG_FILE: str         = os.environ.get("LOG_FILE",   "logs/engine.log")   # [NEW — Step 9]
LOG_MAX_BYTES: int    = 5_000_000  # [NEW — Step 9] 5 MB per log file
LOG_BACKUP_COUNT: int = 3          # [NEW — Step 9] keep 3 rotated files
ALERT_FILE: str       = os.environ.get("ALERT_FILE", "logs/alerts.log")   # [NEW — Step 9]

# ── Engine loop ────────────────────────────────────────────────────────────────
ENGINE_STAGGER_SEC: int         = 2    # sleep between per-pair API calls to avoid rate-limit burst
ENGINE_STRATEGY_BARS: int       = 200  # OHLC bars loaded for strategy signal generation
ENGINE_STRATEGY_MIN_BARS: int   = 50   # minimum cached bars required before running strategy
ENGINE_TRAILING_BARS: int       = 50   # OHLC bars loaded for trailing-stop ATR calculation
ENGINE_TRAILING_ATR_PERIOD: int = 14   # ATR rolling period used in trailing stop

# ── Strategy: Mean Reversion ───────────────────────────────────────────────────
MR_RSI_PERIOD: int       = 14    # RSI lookback period
MR_VWAP_WINDOW: int      = 20    # VWAP rolling window (kept — _vwap still used internally)
MR_BB_PERIOD: int        = 20    # [NEW — Step 18] Bollinger Band rolling window
MR_BB_STD_DEV: float     = 2.0   # [NEW — Step 18] standard deviation multiplier (±2σ ≈ 5% of bars)
MR_ATR_PERIOD: int       = 14    # ATR lookback period
MR_RSI_OVERSOLD: float   = 25.0  # RSI below this → long signal candidate
MR_RSI_OVERBOUGHT: float = 70.0  # RSI above this → short signal candidate [optim2: was 75 → 70 wider MR window]
MR_STOP_ATR_MULT: float  = 1.5   # stop distance = this × ATR              [optim2: was 2.0 → 1.5 tighter MR stops]
MR_TARGET_ATR_MULT: float = 5.0  # target distance = this × ATR  (3.3:1 R/R)

# ── Strategy: Trend Following ──────────────────────────────────────────────────
TF_FAST_EMA_PERIOD: int  = 20    # fast EMA period for crossover
TF_SLOW_EMA_PERIOD: int  = 50    # slow EMA period for crossover
TF_ATR_PERIOD: int       = 14    # ATR lookback period
TF_STOP_ATR_MULT: float  = 3.0   # stop distance = this × ATR                [optim2: was 2.5 → 3.0 wider trend stops]
TF_TARGET_ATR_MULT: float = 8.0  # target distance = this × ATR  (2.7:1 R/R) [optim2: was 6.0 → 8.0 let big trends run]

# ── Strategy: Regime Detection ─────────────────────────────────────────────────
REGIME_ADX_PERIOD: int       = 14   # ADX / DI smoothing period
REGIME_ADX_THRESHOLD: float  = 20.0 # ADX >= this → trending regime [optim: was 25 → 20 more time in trend mode]
REGIME_ATR_PERIOD: int       = 14   # ATR lookback for spike detection
REGIME_ATR_SPIKE_WINDOW: int = 20   # rolling window for baseline ATR mean
REGIME_ATR_SPIKE_MULT: float = 2.0  # current ATR > this × baseline → high_volatility [was 1.5 — too sensitive; minor vol spikes paused all trading]

# ── IG API ─────────────────────────────────────────────────────────────────────
IG_REQUEST_TIMEOUT_SEC: int = 15   # HTTP timeout for all IG REST calls
IG_RETRY_MAX: int           = 3    # [NEW — Step 9] max retries on network errors
IG_RETRY_BASE_SEC: int      = 2    # [NEW — Step 9] base wait for exponential backoff (2/4/8s)

# ── Risk scaling ───────────────────────────────────────────────────────────────
RISK_MIN_SCALE: float        = 0.25  # minimum risk multiplier when soft drawdown is hit
RISK_DD_REDUCTION: float     = 0.75  # fraction of risk removed as drawdown worsens toward hard limit
MIN_STOP_BUFFER: float       = 1.1   # widen stop to IG minimum × this buffer (10 % above minimum)
MAX_RISK_OVERRIDE_MULT: float = 2.0  # [NEW — Step 9] skip trade if min-1-contract risk > 2× intended

# ── Correlation control [NEW — Step 7A] ────────────────────────────────────────
CORR_USD_MAX: int = 1  # max open trades in the same net-USD direction (USD_LONG or USD_SHORT)

# ── Multi-timeframe entry confirmation [NEW — Step 7B] ─────────────────────────
# ── Engine refresh intervals [NEW — Step 8] ────────────────────────────────────
OHLC_REFRESH_INTERVAL_SEC: int  = 600  # incremental OHLC refresh (4 pairs × 2 res = 8 calls/refresh; 600s = 48 calls/hr)
POSITION_SYNC_INTERVAL_SEC: int = 60   # sync IG-closed positions to DB every 60s

# ── Multi-timeframe entry confirmation [NEW — Step 7B] ─────────────────────────
MTF_ENABLED: bool    = True          # set False to bypass without code changes
MTF_RESOLUTION: str  = "MINUTE_5"   # confirmation timeframe (IG resolution string)
MTF_BARS: int        = 60            # 5m bars to load for confirmation (= 5 hours)
MTF_MIN_BARS: int    = 20            # minimum bars needed — pass through if below this
MTF_RSI_PERIOD: int  = 14            # RSI period for 5m confirmation
MTF_EMA_PERIOD: int  = 9             # EMA period for 5m momentum check

# ── Economic Calendar / News Filter [NEW — Step 11] ───────────────────────────
NEWS_FILTER_ENABLED: bool        = True
NEWS_PAUSE_MINUTES: int          = 15                        # pause this many min before AND after event
NEWS_EVENTS_FILE: str            = "data/news_events.json"  # auto-updated by central bank scraper
NEWS_CALENDAR_REFRESH_DAYS: int  = 7                        # re-scrape central bank pages every 7 days
FMP_API_KEY: str                 = os.environ.get("FMP_API_KEY", "")  # paid plan only

# ── COT Report Bias [NEW — Step 10] ──────────────────────────────────────────
COT_ENABLED: bool             = True   # set False to bypass gate entirely
COT_LONG_THRESHOLD: float     = 0.2   # index below this → specs extremely short → bias LONG
COT_SHORT_THRESHOLD: float    = 0.8   # index above this → specs extremely long  → bias SHORT
COT_WEEKS_HISTORY: int        = 52    # rolling window for min/max normalisation
COT_REFRESH_INTERVAL_SEC: int = 3600  # re-download current year file every hour

# ── AI Sentiment [NEW — AI Layer] ───────────────────────────────────────────
FINNHUB_API_KEY: str         = os.environ.get("FINNHUB_API_KEY", "")
SENTIMENT_ENABLED: bool      = bool(FINNHUB_API_KEY and os.environ.get("ANTHROPIC_API_KEY", ""))
SENTIMENT_REFRESH_SEC: int   = 900  # refresh headlines every 15 min during session
SENTIMENT_BLOCK_THRESHOLD: float = 0.5  # block trades when sentiment confidence > this

# ── Telegram Alerts [NEW — Step 13] ──────────────────────────────────────────
TELEGRAM_TOKEN:   str  = os.environ.get("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID: str  = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED: bool = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
