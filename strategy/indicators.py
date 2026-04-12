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


def adx_full(
    df: pd.DataFrame,
    period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    ADX with directional indicators (Wilder smoothing).

    Parameters
    ----------
    df     : DataFrame with columns high, low, close
    period : smoothing period (Wilder: alpha = 1/period)

    Returns
    -------
    (plus_di, minus_di, adx) — all pd.Series.
    plus_di > minus_di → bullish trend, minus_di > plus_di → bearish trend.
    """
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    up_move   = high.diff()
    down_move = -low.diff()

    plus_dm  = np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s  = pd.Series(plus_dm,  index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)

    hl = high - low
    hc = (high - close.shift()).abs()
    lc = (low  - close.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)

    alpha = 1.0 / period
    tr_s     = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di  = 100 * plus_dm_s.ewm(alpha=alpha, adjust=False).mean() / tr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm_s.ewm(alpha=alpha, adjust=False).mean() / tr_s.replace(0, np.nan)

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx     = 100 * (plus_di - minus_di).abs() / di_sum
    adx_val = dx.ewm(alpha=alpha, adjust=False).mean()

    return plus_di, minus_di, adx_val


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


# ── Volume indicators ─────────────────────────────────────────────────────────

def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Money Flow Index — volume-weighted RSI (0-100 scale).

    MFI < 20 → oversold with volume confirmation.
    MFI > 80 → overbought with volume confirmation.
    More reliable than RSI alone because it requires volume to agree.

    Parameters
    ----------
    df     : DataFrame with columns high, low, close, volume
    period : lookback window (standard: 14)

    Returns
    -------
    pd.Series of MFI values.  NaN where not yet warmed up.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    raw_mf = typical_price * df["volume"]

    direction = typical_price.diff()
    pos_mf = raw_mf.where(direction > 0, 0.0).rolling(period).sum()
    neg_mf = raw_mf.where(direction <= 0, 0.0).rolling(period).sum()

    mf_ratio = pos_mf / neg_mf.replace(0, np.nan)
    return 100 - 100 / (1 + mf_ratio)


def obv(df: pd.DataFrame) -> pd.Series:
    """
    On-Balance Volume — cumulative volume flow.

    OBV rises when volume on up-bars exceeds volume on down-bars.
    Divergence between OBV and price signals a trend losing momentum.

    Parameters
    ----------
    df : DataFrame with columns close, volume

    Returns
    -------
    pd.Series of cumulative OBV values.
    """
    direction = np.sign(df["close"].diff())
    return (direction * df["volume"]).fillna(0).cumsum()


def volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Volume ratio — current bar volume / rolling average volume.

    ratio > 1.5 → volume spike (momentum move is serious).
    ratio < 0.5 → quiet market (breakout/crossover less reliable).

    Parameters
    ----------
    df     : DataFrame with column volume
    period : rolling average window (standard: 20)

    Returns
    -------
    pd.Series of volume ratios.  NaN during warmup.
    """
    avg_vol = df["volume"].rolling(period).mean()
    return df["volume"] / avg_vol.replace(0, np.nan)
