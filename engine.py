"""
Forex Engine — main loop.

Runs independently of the dashboard. Lifecycle:
  1. Init DB
  2. Authenticate with IG
  3. Seed historical OHLC (once)
  4. Poll live quotes every QUOTE_INTERVAL_SEC
  5. During session hours: run strategy → risk checks → submit order
"""

from __future__ import annotations

import logging
import signal as _signal
import time
from datetime import datetime, timezone

from core import config, db
from core.ig_client import IGClient
from data.fetcher import fetch_live_quote, seed_history
from execution.gateway import ExecutionGateway
from risk.guard import EquityGuard, PositionSizer, SessionGate, SpreadFilter
from strategy import mean_reversion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("engine")

_running = True


def _shutdown(signum, frame):
    global _running
    log.info("Shutdown signal received — stopping after current loop")
    _running = False


_signal.signal(_signal.SIGINT,  _shutdown)
_signal.signal(_signal.SIGTERM, _shutdown)


def run(dry_run: bool = True) -> None:
    log.info("=" * 60)
    log.info("FOREX ENGINE  |  %s  |  %s",
             config.SYMBOL, "DRY RUN" if dry_run else "LIVE ORDERS")
    log.info("Session: %s–%s UTC  (14:00–18:00 SAST)",
             config.SESSION_START_UTC, config.SESSION_END_UTC)
    log.info("=" * 60)

    # ── Database ──────────────────────────────────────────────────────────────
    db.init_db(config.DB_PATH)
    log.info("Database ready at %s", config.DB_PATH)

    # ── IG client ─────────────────────────────────────────────────────────────
    client = IGClient(
        api_key    = config.IG_API_KEY,
        identifier = config.IG_IDENTIFIER,
        password   = config.IG_PASSWORD,
        account_id = config.IG_ACCOUNT_ID,
        demo       = config.IG_DEMO,
    )
    if not client.authenticate():
        log.error("IG authentication failed — check .env credentials")
        return

    # ── Seed history ─────────────────────────────────────────────────────────
    seed_history(client, config.DB_PATH)

    # ── Risk ──────────────────────────────────────────────────────────────────
    session      = SessionGate()
    spread_filt  = SpreadFilter()
    equity_guard = EquityGuard(config.DB_PATH)
    sizer        = PositionSizer()

    # ── Execution ─────────────────────────────────────────────────────────────
    gateway = ExecutionGateway(
        client       = client,
        db_path      = config.DB_PATH,
        equity_guard = equity_guard,
        sizer        = sizer,
        dry_run      = dry_run,
    )

    log.info("Engine running — polling every %ds  (Ctrl+C to stop)",
             config.QUOTE_INTERVAL_SEC)

    # ── Main loop ─────────────────────────────────────────────────────────────
    while _running:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. Fetch live quote (always — keeps dashboard fresh)
        quote = fetch_live_quote(client, config.DB_PATH)
        if quote is None:
            log.warning("Quote fetch failed — retrying in %ds", config.QUOTE_INTERVAL_SEC)
            time.sleep(config.QUOTE_INTERVAL_SEC)
            continue

        # 2. Session gate
        if not session.is_open(now):
            time.sleep(config.QUOTE_INTERVAL_SEC)
            continue

        # 3. Spread filter
        if not spread_filt.acceptable(quote["spread_pips"]):
            log.info("Spread %.1f pips — too wide, skipping", quote["spread_pips"])
            time.sleep(config.QUOTE_INTERVAL_SEC)
            continue

        # 4. Skip if already in a position
        if db.open_trade(config.DB_PATH, config.SYMBOL):
            time.sleep(config.QUOTE_INTERVAL_SEC)
            continue

        # 5. Load cached bars and run strategy
        bars = db.load_ohlc(config.DB_PATH, config.SYMBOL, "HOUR", limit=200)
        if len(bars) < 50:
            log.warning("Only %d cached bars — need at least 50", len(bars))
            time.sleep(config.QUOTE_INTERVAL_SEC)
            continue

        signal_data = mean_reversion.generate(bars)
        if signal_data:
            signal_id            = db.insert_signal(config.DB_PATH, signal_data)
            signal_data["id"]    = signal_id
            gateway.submit(signal_data)

        time.sleep(config.QUOTE_INTERVAL_SEC)

    log.info("Engine stopped.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Forex Engine")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Submit real orders to IG (default: dry run)",
    )
    args = parser.parse_args()
    run(dry_run=not args.live)
