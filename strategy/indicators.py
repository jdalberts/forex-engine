"""
[NEW — Step 9] Shared technical indicators used across all strategy modules.

Centralising here eliminates the copy-paste duplication of _atr() and _rsi()
that previously existed in mean_reversion, trend_following, regime_detection,
and mtf_filter.  Any future indicator fixes apply automatically everywhere.

Usage:
    from strategy.indicators import atr, rsi
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Average True Range (simple rolling mean of True Range).

    Parameters
    ----------
    df     : DataFrame with columns high, low, close
    period : rolling window size

    Returns
    -------
    pd.Series of ATR values (NaN for first `period` rows)
    """
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    """
    Relative Strength Index (Wilder EWM smoothing).

    Parameters
    ----------
    close  : price series
    period : lookback window (Wilder: alpha = 1/period)

    Returns
    -------
    pd.Series of RSI values (0–100).  NaN where not yet warmed up.
    Note: callers that need NaN filled to 50 should do so locally.
    """
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def bollinger_bands(
    close: pd.Series,
    period: int,
    num_std: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands — upper, middle, lower.  [NEW — Step 18]

    Parameters
    ----------
    close   : price series
    period  : rolling window for mean and std
    num_std : number of standard deviations for the bands

    Returns
    -------
    (upper, middle, lower) — each a pd.Series aligned to `close`.
    NaN for the first period-1 rows (warmup).  Callers handle NaN.
    middle = rolling mean; bands = middle ± num_std × rolling std (ddof=1).
    """
    middle = close.rolling(period).mean()
    std    = close.rolling(period).std()          # ddof=1 is pandas default
    upper  = middle + num_std * std
    lower  = middle - num_std * std
    return upper, middle, lower


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD — line, signal, histogram.

    Parameters
    ----------
    close  : price series
    fast   : fast EMA period
    slow   : slow EMA period
    signal : signal line EMA period

    Returns
    -------
    (macd_line, signal_line, histogram) — each a pd.Series.
    histogram = macd_line - signal_line.
    Positive histogram = bullish momentum, negative = bearish.
    Shrinking histogram = momentum fading (good for mean reversion entry).
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram
