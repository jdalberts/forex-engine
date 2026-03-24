"""Central configuration — loaded once from .env."""

from __future__ import annotations

import os
from datetime import time as dtime

from dotenv import load_dotenv

load_dotenv()

# ── IG credentials ────────────────────────────────────────────────────────────
IG_API_KEY: str     = os.environ["IG_API_KEY"]
IG_IDENTIFIER: str  = os.environ["IG_IDENTIFIER"]
IG_PASSWORD: str    = os.environ["IG_PASSWORD"]
IG_ACCOUNT_ID: str  = os.environ.get("IG_ACCOUNT_ID", "Z69JGB")
IG_DEMO: bool       = os.environ.get("IG_DEMO", "true").lower() == "true"

# ── Instruments ───────────────────────────────────────────────────────────────
# All share the London/NY overlap window (14:00–18:00 SAST)
# pip_value_usd: USD value per pip per 1 standard contract (100,000 base units)
#   EUR/USD: 100,000 × 0.0001 = $10
#   GBP/USD: 100,000 × 0.0001 = $10 (GBP quoted in USD)
#   USD/CHF: 100,000 × 0.0001 = CHF10 → ~$12.50 at 0.80 USDCHF
#   GBP/JPY: 100,000 × 0.01   = JPY1000 → ~$6.30 at 158 USDJPY
PAIRS: dict = {
    # price_scale: divide raw IG snapshot/OHLC price by this to get actual FX rate.
    # EUR/USD CFD is quoted as ×10000 by IG (/markets and /prices return 11510 → 1.1510).
    # The other pairs are returned in human-readable format by IG, so price_scale=1.
    "EURUSD": {"epic": "CS.D.EURUSD.CFD.IP", "currency": "USD", "pip_size": 0.0001, "pip_value_usd": 10.0,  "price_scale": 10000},
    "GBPUSD": {"epic": "CS.D.GBPUSD.CFD.IP", "currency": "USD", "pip_size": 0.0001, "pip_value_usd": 10.0,  "price_scale": 1},
    "USDCHF": {"epic": "CS.D.USDCHF.CFD.IP", "currency": "CHF", "pip_size": 0.0001, "pip_value_usd": 12.5,  "price_scale": 1},
    "GBPJPY": {"epic": "CS.D.GBPJPY.CFD.IP", "currency": "JPY", "pip_size": 0.01,   "pip_value_usd":  6.3,  "price_scale": 1},
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
TRAILING_ATR_MULT: float = 1.2     # [NEW — Step 5] trailing stop distance in ATR units (trending trades) [was 0.8 — too tight, stopped trend trades early]

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
MR_VWAP_WINDOW: int      = 20    # VWAP rolling window
MR_ATR_PERIOD: int       = 14    # ATR lookback period
MR_RSI_OVERSOLD: float   = 30.0  # RSI below this → long signal candidate  [was 35.0 — tighter filter, fewer but higher-conviction longs]
MR_RSI_OVERBOUGHT: float = 70.0  # RSI above this → short signal candidate [was 65.0 — tighter filter, fewer but higher-conviction shorts]
MR_STOP_ATR_MULT: float  = 1.5   # stop distance = this × ATR              [was 0.8 — stops were too tight, frequently stopped out by noise]
MR_TARGET_ATR_MULT: float = 3.0  # target distance = this × ATR  (2 : 1 R/R) [was 1.6 — target too small relative to stop; now 2:1 R/R maintained]

# ── Strategy: Trend Following ──────────────────────────────────────────────────
TF_FAST_EMA_PERIOD: int  = 12    # fast EMA period for crossover              [was 9 — 12/26 is the standard MACD signal pair, more reliable]
TF_SLOW_EMA_PERIOD: int  = 26    # slow EMA period for crossover              [was 21 — paired with fast=12 for MACD-style crossover]
TF_ATR_PERIOD: int       = 14    # ATR lookback period
TF_STOP_ATR_MULT: float  = 2.0   # stop distance = this × ATR                [was 0.8 — trend trades need room; 2× ATR avoids premature stop-outs]
TF_TARGET_ATR_MULT: float = 4.0  # target distance = this × ATR  (2 : 1 R/R) [was 1.6 — 4× ATR target with 2× ATR stop maintains 2:1 R/R]

# ── Strategy: Regime Detection ─────────────────────────────────────────────────
REGIME_ADX_PERIOD: int       = 14   # ADX / DI smoothing period
REGIME_ADX_THRESHOLD: float  = 25.0 # ADX >= this → trending regime
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

# ── Telegram Alerts [NEW — Step 13] ──────────────────────────────────────────
TELEGRAM_TOKEN:   str  = os.environ.get("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID: str  = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED: bool = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
