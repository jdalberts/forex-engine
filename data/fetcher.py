"""Data layer — seed historical OHLC and poll live quotes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from core import config, db
from core.ig_client import IGClient

log = logging.getLogger(__name__)


def seed_history(
    client: IGClient,
    db_path: str     = config.DB_PATH,
    symbol: str      = "EURUSD",
    epic: str        = "CS.D.EURUSD.CFD.IP",
    price_scale: int = 1,
    resolution: str  = "HOUR",   # [NEW — Step 7B] any IG resolution string
) -> int:
    """
    Download historical OHLC from IG and cache to SQLite.
    Skips if data already exists — safe to call on every startup.
    Pass resolution="MINUTE_5" for the multi-timeframe confirmation layer.
    """
    existing = db.latest_ohlc_time(db_path, symbol, resolution)
    if existing:
        count = db.count_ohlc(db_path, symbol, resolution)
        log.info("OHLC cache already has %d %s bars (latest: %s) — skipping seed [%s]",
                 count, resolution, existing, symbol)
        return 0

    log.info("Seeding %d %s historical bars for %s…", config.HISTORY_BARS, resolution, symbol)
    bars = client.get_history(epic, resolution=resolution, max_bars=config.HISTORY_BARS,
                              price_scale=price_scale)

    if not bars:
        log.error("IG returned no historical bars — check credentials and epic [%s %s]",
                  symbol, resolution)
        return 0

    inserted = db.upsert_ohlc(db_path, symbol, resolution, bars)
    log.info("Cached %d %s bars to SQLite [%s]", inserted, resolution, symbol)
    return inserted


def refresh_bars(
    client: IGClient,
    db_path: str,
    symbol: str,
    epic: str,
    price_scale: int = 1,
    resolution: str  = "HOUR",
) -> int:
    """
    [NEW — Step 8] Incrementally fetch bars newer than the latest stored timestamp.

    Safe to call every engine loop — returns 0 immediately if no new bars exist
    or if the seed has not run yet.  Uses ig_client.get_history(from_time=...)
    so only bars since the last cached bar are requested.
    """
    latest = db.latest_ohlc_time(db_path, symbol, resolution)
    if latest is None:
        return 0   # seed_history() has not run yet — nothing to refresh against

    # Parse latest stored time, add 1 s buffer to avoid re-fetching the same bar
    from_time = datetime.fromisoformat(latest) + timedelta(seconds=1)

    # Guard: never request bars in the future
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if from_time >= now:
        return 0

    bars = client.get_history(
        epic, resolution=resolution, max_bars=100,
        price_scale=price_scale, from_time=from_time,
    )
    if not bars:
        return 0

    inserted = db.upsert_ohlc(db_path, symbol, resolution, bars)
    if inserted:
        log.info("Refreshed %d new %s bars for %s", inserted, resolution, symbol)
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
