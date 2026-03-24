"""
[NEW — Step 2] Market regime detection.

Classifies current market conditions into one of three regimes:

    "ranging"         — ADX < ADX_TREND_THRESHOLD (market is flat/choppy)
    "trending"        — ADX >= ADX_TREND_THRESHOLD (market has directional momentum)
    "high_volatility" — ATR spike: current ATR > ATR_SPIKE_MULT × rolling ATR mean
                        (unusual volatility — step back and wait)

Priority: high_volatility is checked first. If ATR is spiking, regime is
"high_volatility" regardless of ADX value.

NOT connected to the trading loop yet — this module is standalone.
Call detect_market_regime(bars) from anywhere to get the current regime string.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np
import pandas as pd

from core import config
from strategy.indicators import atr as _atr_shared  # [NEW — Step 9]

log = logging.getLogger(__name__)

# ── [NEW] Parameters (sourced from config — edit values in core/config.py) ────
ADX_PERIOD          = config.REGIME_ADX_PERIOD        # lookback for ADX / DI smoothing
ADX_TREND_THRESHOLD = config.REGIME_ADX_THRESHOLD     # ADX >= this  →  trending
ATR_PERIOD          = config.REGIME_ATR_PERIOD         # lookback for ATR
ATR_SPIKE_WINDOW    = config.REGIME_ATR_SPIKE_WINDOW   # rolling window for baseline ATR mean
ATR_SPIKE_MULT      = config.REGIME_ATR_SPIKE_MULT     # current ATR > this × baseline  →  high_volatility
MIN_BARS            = ADX_PERIOD + ATR_SPIKE_WINDOW + 5   # minimum bars needed

Regime = Literal["ranging", "trending", "high_volatility"]


# ── [NEW] Indicators ──────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """Delegates to shared strategy.indicators.atr — [NEW — Step 9]."""
    return _atr_shared(df, period)


def _adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    """
    Average Directional Index (Wilder smoothing).

    Returns a Series of ADX values aligned to df's index.
    Values below period*2 rows will be NaN — need enough bars to warm up.
    """
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    # Directional movement
    up_move   = high.diff()
    down_move = -low.diff()

    plus_dm  = np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s  = pd.Series(plus_dm,  index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)

    # True Range
    hl = high - low
    hc = (high - close.shift()).abs()
    lc = (low  - close.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)

    # Wilder smoothing: equivalent to EWM with alpha = 1/period
    alpha = 1.0 / period
    tr_s     = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di  = 100 * plus_dm_s.ewm(alpha=alpha, adjust=False).mean() / tr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm_s.ewm(alpha=alpha, adjust=False).mean() / tr_s.replace(0, np.nan)

    # DX and ADX
    di_sum  = (plus_di + minus_di).replace(0, np.nan)
    dx      = 100 * (plus_di - minus_di).abs() / di_sum
    adx     = dx.ewm(alpha=alpha, adjust=False).mean()

    return adx


# ── [NEW] Regime detection ────────────────────────────────────────────────────

def detect_market_regime(bars: list[dict]) -> Regime:
    """
    Classify current market conditions.

    Parameters
    ----------
    bars : list of OHLCV dicts — same format used by mean_reversion.generate()

    Returns
    -------
    "ranging"         — ADX < ADX_TREND_THRESHOLD (choppy, mean reversion favoured)
    "trending"        — ADX >= ADX_TREND_THRESHOLD (directional, trend following favoured)
    "high_volatility" — ATR spiking above baseline (pause, no trades)

    Logs a WARNING and returns "ranging" (safe default) if there are not enough bars.
    """
    if len(bars) < MIN_BARS:
        log.warning(
            "[regime] Not enough bars (%d/%d) — defaulting to 'ranging'",
            len(bars), MIN_BARS,
        )
        return "ranging"

    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)

    atr_series = _atr(df)
    adx_series = _adx(df)

    current_atr = float(atr_series.iloc[-1])
    baseline_atr = float(atr_series.iloc[-ATR_SPIKE_WINDOW:].mean())
    current_adx = float(adx_series.iloc[-1])

    # ── Determine regime ──────────────────────────────────────────────────────
    # Priority: high_volatility > trending > ranging

    if pd.isna(current_atr) or pd.isna(current_adx):
        log.warning("[regime] Indicators not ready (NaN) — defaulting to 'ranging'")
        return "ranging"

    atr_spike = (baseline_atr > 0) and (current_atr > ATR_SPIKE_MULT * baseline_atr)

    if atr_spike:
        regime: Regime = "high_volatility"
    elif current_adx >= ADX_TREND_THRESHOLD:
        regime = "trending"
    else:
        regime = "ranging"

    log.info(
        "[regime] ADX=%.1f (threshold=%d)  ATR=%.5f  baseline_ATR=%.5f  ->  %s",
        current_adx, ADX_TREND_THRESHOLD,
        current_atr, baseline_atr,
        regime.upper(),
    )

    return regime
