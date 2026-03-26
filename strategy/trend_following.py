"""
[NEW — Step 3] Trend following strategy — EMA crossover.

Entry rules:
  LONG  : fast EMA crosses ABOVE slow EMA  (bullish momentum)
  SHORT : fast EMA crosses BELOW slow EMA  (bearish momentum)

Sizing (same ATR-based formula as mean_reversion):
  Stop   : 0.8 × ATR from entry
  Target : 1.6 × ATR from entry  (2 : 1 reward/risk)

Signal dict format is identical to mean_reversion.generate() so it can flow
through the existing ExecutionGateway and DB layer unchanged.

Pre-existing fix compliance:
  Fix 2 (stopDistance/limitDistance): signal passes stop/target as price levels;
         ig_client.place_order() converts them to distances — no change needed here.
  Fix 3 (min deal size): sizing goes through PositionSizer.lot_size() in gateway —
         no change needed here.

NOT connected to the trading loop yet — standalone function only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from core import config
from strategy.indicators import atr as _atr_shared  # [NEW — Step 9]
from strategy.regime_detection import _adx_full

log = logging.getLogger(__name__)

# ── [NEW] Parameters (sourced from config — edit values in core/config.py) ────
FAST_EMA_PERIOD  = config.TF_FAST_EMA_PERIOD   # fast EMA lookback
SLOW_EMA_PERIOD  = config.TF_SLOW_EMA_PERIOD   # slow EMA lookback
ATR_PERIOD       = config.TF_ATR_PERIOD         # ATR lookback
STOP_ATR_MULT    = config.TF_STOP_ATR_MULT      # stop distance in ATR units
TARGET_ATR_MULT  = config.TF_TARGET_ATR_MULT    # target distance in ATR units (2:1 R)
MIN_BARS         = SLOW_EMA_PERIOD + ATR_PERIOD + 5  # minimum bars needed


# ── [NEW] Indicators ──────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average using pandas EWM (span = period)."""
    return series.ewm(span=period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """Delegates to shared strategy.indicators.atr — [NEW — Step 9]."""
    return _atr_shared(df, period)


# ── [NEW] Signal generation ───────────────────────────────────────────────────

def trend_following_signal(bars: list[dict]) -> Optional[dict]:
    """
    Evaluate the latest bar for an EMA crossover signal.

    Returns a signal dict (same keys as mean_reversion.generate()) or None.

    A crossover is only triggered on the bar where the crossover JUST happened
    (previous bar had the opposite alignment) to avoid repeated signals during
    a sustained trend.

    Signal keys:
        symbol, strategy, direction, entry, stop, target, atr, reason, generated_at
    """
    if len(bars) < MIN_BARS:
        log.debug(
            "[trend] Not enough bars (%d/%d) for trend following",
            len(bars), MIN_BARS,
        )
        return None

    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)

    df["fast_ema"] = _ema(df["close"], FAST_EMA_PERIOD)
    df["slow_ema"] = _ema(df["close"], SLOW_EMA_PERIOD)
    df["atr"]      = _atr(df)

    # ADX direction indicators for trend confirmation
    plus_di, minus_di, _ = _adx_full(df)

    # Current and previous bar values
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    fast_now  = float(curr["fast_ema"])
    slow_now  = float(curr["slow_ema"])
    fast_prev = float(prev["fast_ema"])
    slow_prev = float(prev["slow_ema"])
    close     = float(curr["close"])
    atr       = float(curr["atr"])

    if pd.isna(atr) or atr <= 0:
        log.debug("[trend] ATR not ready")
        return None

    # ── Crossover detection ───────────────────────────────────────────────────
    # A crossover occurs only on the bar where alignment flips
    bullish_cross = (fast_now > slow_now) and (fast_prev <= slow_prev)
    bearish_cross = (fast_now < slow_now) and (fast_prev >= slow_prev)

    direction: Optional[str] = None
    reason:    Optional[str] = None

    if bullish_cross:
        direction = "long"
        reason = (
            f"EMA cross UP: fast({FAST_EMA_PERIOD})={fast_now:.5f} "
            f"> slow({SLOW_EMA_PERIOD})={slow_now:.5f}"
        )
    elif bearish_cross:
        direction = "short"
        reason = (
            f"EMA cross DOWN: fast({FAST_EMA_PERIOD})={fast_now:.5f} "
            f"< slow({SLOW_EMA_PERIOD})={slow_now:.5f}"
        )

    if direction is None:
        return None

    # ── ADX direction filter — confirm trend with +DI/-DI ────────────────────
    pdi = float(plus_di.iloc[-1])
    mdi = float(minus_di.iloc[-1])
    if not pd.isna(pdi) and not pd.isna(mdi):
        if direction == "long" and pdi <= mdi:
            log.info("[trend] Bullish cross blocked — -DI (%.1f) > +DI (%.1f)", mdi, pdi)
            return None
        if direction == "short" and mdi <= pdi:
            log.info("[trend] Bearish cross blocked — +DI (%.1f) > -DI (%.1f)", pdi, mdi)
            return None

    # ── Stop and target (ATR-based, same as mean_reversion) ───────────────────
    entry = close
    if direction == "long":
        stop   = round(entry - STOP_ATR_MULT   * atr, 5)
        target = round(entry + TARGET_ATR_MULT * atr, 5)
    else:
        stop   = round(entry + STOP_ATR_MULT   * atr, 5)
        target = round(entry - TARGET_ATR_MULT * atr, 5)

    signal = {
        "symbol":       "",   # overwritten by engine per-pair
        "strategy":     "trend_following",
        "direction":    direction,
        "entry":        round(entry, 5),
        "stop":         stop,
        "target":       target,
        "atr":          round(atr, 5),
        "reason":       reason,
        "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }

    log.info(
        "[trend] Signal: %s @ %.5f  stop %.5f  target %.5f  |  %s",
        direction.upper(), entry, stop, target, reason,
    )
    return signal
