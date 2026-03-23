"""Data layer — seed historical OHLC and poll live quotes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from core import config, db
from core.ig_client import IGClient

log = logging.getLogger(__name__)


def seed_history(
    client: IGClient,
    db_path: str    = config.DB_PATH,
    symbol: str     = "EURUSD",
    epic: str       = "CS.D.EURUSD.CFD.IP",
    price_scale: int = 1,
) -> int:
    """
    Download historical OHLC from IG and cache to SQLite.
    Skips if data already exists — safe to call on every startup.
    """
    existing = db.latest_ohlc_time(db_path, symbol, "HOUR")
    if existing:
        count = db.count_ohlc(db_path, symbol, "HOUR")
        log.info("OHLC cache already has %d bars (latest: %s) — skipping seed [%s]", count, existing, symbol)
        return 0

    log.info("Seeding %d historical bars for %s…", config.HISTORY_BARS, symbol)
    bars = client.get_history(epic, resolution="HOUR", max_bars=config.HISTORY_BARS,
                              price_scale=price_scale)

    if not bars:
        log.error("IG returned no historical bars — check credentials and epic [%s]", symbol)
        return 0

    inserted = db.upsert_ohlc(db_path, symbol, "HOUR", bars)
    log.info("Cached %d OHLC bars to SQLite [%s]", inserted, symbol)
    return inserted


def fetch_live_quote(
    client: IGClient,
    db_path: str     = config.DB_PATH,
    symbol: str      = "EURUSD",
    epic: str        = "CS.D.EURUSD.CFD.IP",
    pip_size: float  = 0.0001,
    price_scale: int = 1,
) -> dict | None:
    """
    Fetch the current bid/ask from IG /markets endpoint,
    persist to the quotes table, and return the enriched quote.
    price_scale is passed explicitly from config — see PAIRS["price_scale"].
    """
    quote = client.get_snapshot(epic, price_scale=price_scale)
    if quote is None:
        return None

    spread_pips = (quote["ask"] - quote["bid"]) / pip_size
    quote["spread_pips"] = round(spread_pips, 1)

    db.insert_quote(db_path, symbol, quote["bid"], quote["ask"], quote["time"])
    return quote
