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

# ── Instrument ────────────────────────────────────────────────────────────────
SYMBOL      = "EURUSD"
EPIC        = "CS.D.EURUSD.CFD.IP"
CURRENCY    = "USD"
PIP_SIZE    = 0.0001        # 1 pip for EUR/USD
PRICE_SCALE = 10000         # IG quotes EUR/USD CFD as integer ×10000 (11510 = 1.1510)

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
QUOTE_INTERVAL_SEC  = 5            # live quote polling interval
