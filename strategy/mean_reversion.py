"""
Mean reversion strategy — RSI + VWAP on 1h bars.

Entry rules:
  LONG  : RSI < 35  AND  close < VWAP  (oversold + below fair value)
  SHORT : RSI > 65  AND  close > VWAP  (overbought + above fair value)

Sizing:
  Stop   : 0.8 × ATR from entry
  Target : 1.6 × ATR from entry  (2 : 1 reward/risk)

Filters applied before signal is emitted:
  - Minimum bar count (need enough history for indicators)
  - ATR must be positive (market must be moving)
  - No signal within 3 bars of the last signal (cooldown)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from core import config
from strategy.indicators import atr as _atr_shared, rsi as _rsi_shared, bollinger_bands as _bb_shared  # [NEW — Step 9 / Step 18]

log = logging.getLogger(__name__)

# ── Parameters (sourced from config — edit values in core/config.py) ──────────
RSI_PERIOD      = config.MR_RSI_PERIOD
VWAP_WINDOW     = config.MR_VWAP_WINDOW
BB_PERIOD       = config.MR_BB_PERIOD       # [NEW — Step 18]
BB_STD_DEV      = config.MR_BB_STD_DEV      # [NEW — Step 18]
ATR_PERIOD      = config.MR_ATR_PERIOD
RSI_OVERSOLD    = config.MR_RSI_OVERSOLD
RSI_OVERBOUGHT  = config.MR_RSI_OVERBOUGHT
STOP_ATR_MULT   = config.MR_STOP_ATR_MULT
TARGET_ATR_MULT = config.MR_TARGET_ATR_MULT  # 2 : 1 R
MIN_BARS        = RSI_PERIOD + BB_PERIOD + 5  # [Step 18] was VWAP_WINDOW (same value: 39)


# ── Indicators ────────────────────────────────────────────────────────────────
# [NEW — Step 9] Delegates to strategy.indicators — no local copies.

def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    return _atr_shared(df, period)


def _rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    return _rsi_shared(series, period).fillna(50)  # fillna(50) = neutral on warmup


def _bb(df: pd.DataFrame, period: int = BB_PERIOD,
        num_std: float = BB_STD_DEV) -> tuple:
    """Bollinger Bands wrapper — delegates to strategy.indicators. [NEW — Step 18]"""
    return _bb_shared(df["close"], period, num_std)


def _vwap(df: pd.DataFrame, window: int = VWAP_WINDOW) -> pd.Series:
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    vol = df.get("volume", pd.Series(1.0, index=df.index))
    # FX data (Yahoo Finance, IG CFD) has zero volume — use uniform weighting
    # so VWAP degrades gracefully to a rolling average price.
    vol = vol.where(vol > 0, 1.0)
    cum_tpv = (tp * vol).rolling(window).sum()
    cum_v   = vol.rolling(window).sum().replace(0, np.nan)
    return (cum_tpv / cum_v).bfill()


# ── Signal generation ─────────────────────────────────────────────────────────

def generate(bars: list[dict]) -> Optional[dict]:
    """
    Evaluate the latest bar and return a signal dict or None.

    Signal keys:
        symbol, strategy, direction, entry, stop, target, reason, generated_at
    """
    if len(bars) < MIN_BARS:
        log.debug("Not enough bars (%d/%d) for mean reversion", len(bars), MIN_BARS)
        return None

    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)

    df["rsi"]  = _rsi(df["close"])
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = _bb(df)   # [Step 18] replaced VWAP
    df["atr"]  = _atr(df)

    last     = df.iloc[-1]
    rsi      = float(last["rsi"])
    bb_upper = float(last["bb_upper"])
    bb_lower = float(last["bb_lower"])
    close    = float(last["close"])
    atr      = float(last["atr"])

    if pd.isna(atr) or atr <= 0 or pd.isna(bb_upper) or pd.isna(bb_lower):
        log.debug("Indicators not ready (ATR or BB)")
        return None

    direction: Optional[str] = None
    reason:    Optional[str] = None

    if rsi < RSI_OVERSOLD and close <= bb_lower:
        direction = "long"
        reason    = (f"RSI {rsi:.1f} < {RSI_OVERSOLD} | "
                     f"close {close:.5f} <= BB_lower {bb_lower:.5f}")
    elif rsi > RSI_OVERBOUGHT and close >= bb_upper:
        direction = "short"
        reason    = (f"RSI {rsi:.1f} > {RSI_OVERBOUGHT} | "
                     f"close {close:.5f} >= BB_upper {bb_upper:.5f}")

    if direction is None:
        return None

    if direction == "long":
        entry  = close
        stop   = round(entry - STOP_ATR_MULT   * atr, 5)
        target = round(entry + TARGET_ATR_MULT * atr, 5)
    else:
        entry  = close
        stop   = round(entry + STOP_ATR_MULT   * atr, 5)
        target = round(entry - TARGET_ATR_MULT * atr, 5)

    signal = {
        "symbol":       "",   # overwritten by engine per-pair
        "strategy":     "mean_reversion",
        "direction":    direction,
        "entry":        round(entry, 5),
        "stop":         stop,
        "target":       target,
        "atr":          round(atr, 5),   # included so engine can recalc vs live price
        "reason":       reason,
        "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }

    log.info(
        "Signal: %s @ %.5f  stop %.5f  target %.5f  |  %s",
        direction.upper(), entry, stop, target, reason,
    )
    return signal
