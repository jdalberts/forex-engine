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
INITIAL_BALANCE: float  = 20_000.0
RISK_PER_TRADE: float   = 0.005    # 0.5 % of account per trade
SOFT_DRAWDOWN: float    = 0.02     # 2 % → scale risk down to 25 %
HARD_DRAWDOWN: float    = 0.04     # 4 % → halt trading entirely
MAX_SPREAD_PIPS: float  = 2.0      # reject if spread wider than 2 pips

# ── Data ──────────────────────────────────────────────────────────────────────
DB_PATH: str        = os.environ.get("DB_PATH", "data/forex_engine.db")
HISTORY_BARS: int   = 500          # bars to seed on first run
QUOTE_INTERVAL_SEC  = 15           # live quote polling interval (4 pairs × 4/min = safe)
