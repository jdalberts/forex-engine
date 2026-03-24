"""
[NEW — Step 17] Yahoo Finance OHLC fetcher for backtesting.

Downloads up to ~2 years of hourly FX data from Yahoo Finance.
Free, no API key, no rate limits for reasonable use.

Returns bars in the same {time, open, high, low, close, volume} format
as the IG fetcher so backtest.py can use either source without changes.

Ticker mapping:
    EURUSD → EURUSD=X
    GBPUSD → GBPUSD=X
    USDCHF → USDCHF=X
    GBPJPY → GBPJPY=X

Limitations:
    - Yahoo caps hourly FX data at ~730 days (≈1,500 trading bars)
    - Prices are interbank mid-prices, not IG CFD prices — close enough for
      strategy validation; a small spread cost isn't modelled here
    - Volume is always 0 for FX on Yahoo (no centralised FX exchange)
    - Occasional gaps (holidays, data outages) are dropped automatically

Usage:
    from data.yahoo_fetcher import fetch_yahoo_bars
    bars = fetch_yahoo_bars("EURUSD", max_bars=1500)
"""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# Yahoo Finance ticker symbols for each pair
YAHOO_TICKERS: dict[str, str] = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDCHF": "USDCHF=X",
    "GBPJPY": "GBPJPY=X",
}


def fetch_yahoo_bars(symbol: str, max_bars: int = 1500) -> list[dict]:
    """
    Download hourly OHLC bars from Yahoo Finance for the given FX symbol.

    Parameters
    ----------
    symbol   : one of EURUSD, GBPUSD, USDCHF, GBPJPY
    max_bars : cap on bars returned (Yahoo caps at ~1,500 for 1h / 2y anyway)

    Returns
    -------
    List of dicts with keys: time, open, high, low, close, volume
    Sorted oldest-first, weekends removed, NaN rows dropped.
    Returns [] on any error.
    """
    ticker = YAHOO_TICKERS.get(symbol.upper())
    if not ticker:
        log.error("Yahoo fetcher: unknown symbol '%s'. Known: %s",
                  symbol, list(YAHOO_TICKERS))
        return []

    log.info("[%s] Downloading Yahoo Finance hourly bars (ticker=%s, period=2y)…",
             symbol, ticker)
    try:
        df = yf.download(
            tickers  = ticker,
            period   = "2y",        # maximum available for hourly data
            interval = "1h",
            auto_adjust = True,     # adjust for splits/dividends (irrelevant for FX)
            progress = False,       # suppress yfinance progress bar
        )
    except Exception as exc:
        log.error("[%s] Yahoo download failed: %s", symbol, exc)
        return []

    if df is None or df.empty:
        log.warning("[%s] Yahoo returned empty DataFrame", symbol)
        return []

    # Flatten MultiIndex columns if present (yfinance 0.2+ returns MultiIndex)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Normalise column names to lowercase
    df.columns = [c.lower() for c in df.columns]

    required = {"open", "high", "low", "close"}
    if not required.issubset(set(df.columns)):
        log.error("[%s] Yahoo DataFrame missing columns. Got: %s", symbol, list(df.columns))
        return []

    # Drop rows with any NaN in OHLC (occasional gaps in Yahoo FX data)
    df = df.dropna(subset=["open", "high", "low", "close"])

    # Convert index to UTC-naive datetime string
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)

    # Remove weekend bars (Saturday=5, Sunday=6)
    df = df[df.index.dayofweek < 5]

    if df.empty:
        log.warning("[%s] No bars remaining after cleaning", symbol)
        return []

    # Cap to max_bars (take the most recent)
    if len(df) > max_bars:
        df = df.iloc[-max_bars:]

    bars = [
        {
            "time":   str(ts)[:19],           # "YYYY-MM-DD HH:MM:SS"
            "open":   round(float(row["open"]),  6),
            "high":   round(float(row["high"]),  6),
            "low":    round(float(row["low"]),   6),
            "close":  round(float(row["close"]), 6),
            "volume": 0,
        }
        for ts, row in df.iterrows()
    ]

    log.info("[%s] Yahoo: %d bars  (%s → %s)",
             symbol, len(bars), bars[0]["time"][:10], bars[-1]["time"][:10])
    return bars
