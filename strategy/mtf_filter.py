"""
[NEW — Step 7B] Multi-timeframe entry confirmation filter.

Called after the 1h strategy signal is generated.  Loads 5-minute bars and
checks that the short-term structure agrees with the signal direction before
allowing entry.

Confirmation logic (OR — either condition is sufficient):
  Long:  5m RSI < 60  (room to run, not already overbought)
         OR  5m EMA slope is rising over the last 3 bars
  Short: 5m RSI > 40  (room to fall, not already oversold)
         OR  5m EMA slope is falling over the last 3 bars

Pass-through rules (return True without blocking):
  - Fewer than MTF_MIN_BARS bars available
  - RSI indicator returns NaN (insufficient warm-up)
These prevent the filter from blocking trades due to missing data.
"""

from __future__ import annotations

import logging

import pandas as pd

from core import config
from strategy.indicators import rsi as _rsi_shared  # [NEW — Step 9]

log = logging.getLogger(__name__)


def _rsi(close: pd.Series, period: int) -> pd.Series:
    """Delegates to shared strategy.indicators.rsi — [NEW — Step 9]."""
    return _rsi_shared(close, period)


def confirm_entry(signal_data: dict, bars_5m: list[dict]) -> bool:
    """
    [NEW — Step 7B] Confirm a 1h signal using 5-minute bar structure.

    Parameters
    ----------
    signal_data : signal dict from select_strategy() — must contain "direction"
    bars_5m     : list of 5m OHLCV dicts from db.load_ohlc(..., "MINUTE_5")

    Returns
    -------
    True  — signal confirmed (or insufficient data — pass through)
    False — 5m structure contradicts signal; caller should discard signal
    """
    direction = signal_data.get("direction", "")
    symbol    = signal_data.get("symbol", "?")

    if len(bars_5m) < config.MTF_MIN_BARS:
        log.info("[mtf] %s — insufficient 5m bars (%d/%d) — passing through",
                 symbol, len(bars_5m), config.MTF_MIN_BARS)
        return True

    df      = pd.DataFrame(bars_5m)
    rsi_ser = _rsi(df["close"], config.MTF_RSI_PERIOD)
    ema_ser = df["close"].ewm(span=config.MTF_EMA_PERIOD, adjust=False).mean()

    current_rsi = float(rsi_ser.iloc[-1])

    if pd.isna(current_rsi):
        log.info("[mtf] %s — RSI not ready (NaN) — passing through", symbol)
        return True

    ema_rising = float(ema_ser.iloc[-1]) > float(ema_ser.iloc[-3])

    if direction == "long":
        rsi_ok = current_rsi < 60
        ema_ok = ema_rising
    elif direction == "short":
        rsi_ok = current_rsi > 40
        ema_ok = not ema_rising
    else:
        return True   # unknown direction — pass through

    confirmed = rsi_ok or ema_ok

    log.info(
        "[mtf] %s %s  5m_RSI=%.1f  ema_slope=%s  rsi_ok=%s  ema_ok=%s  -> %s",
        symbol, direction.upper(),
        current_rsi,
        "up" if ema_rising else "down",
        rsi_ok, ema_ok,
        "CONFIRMED" if confirmed else "REJECTED",
    )
    return confirmed
