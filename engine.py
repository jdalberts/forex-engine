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
    pairs = config.PAIRS
    symbols = list(pairs.keys())

    log.info("=" * 60)
    log.info("FOREX ENGINE  |  %s  |  %s",
             ", ".join(symbols), "DRY RUN" if dry_run else "LIVE ORDERS")
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

    # ── Sync: close DB trades that IG already closed ──────────────────────────
    ig_open = {p["market"]["epic"] for p in client.get_open_positions()}
    for symbol, pcfg in pairs.items():
        db_trade = db.open_trade(config.DB_PATH, symbol)
        if db_trade and pcfg["epic"] not in ig_open:
            # Estimate PnL from last known quote
            quote = db.latest_quote(config.DB_PATH, symbol)
            if quote:
                mid   = (float(quote["bid"]) + float(quote["ask"])) / 2
                entry = float(db_trade["entry_price"])
                size  = float(db_trade["size"])
                pnl   = round((mid - entry) * size if db_trade["direction"] == "long"
                              else (entry - mid) * size, 2)
            else:
                pnl = 0.0
            db.close_trade(config.DB_PATH, db_trade["id"], exit_price=mid if quote else entry, pnl=pnl)
            log.info("[%s] Position closed on IG — synced DB  estimated_pnl=%.2f", symbol, pnl)

    # ── Seed history for all pairs ────────────────────────────────────────────
    for symbol, pcfg in pairs.items():
        seed_history(client, config.DB_PATH, symbol=symbol, epic=pcfg["epic"])

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
        in_session = session.is_open(now)

        for symbol, pcfg in pairs.items():
            time.sleep(2)   # stagger API calls — avoids IG rate limit burst

            # 1. Fetch live quote (always — keeps dashboard fresh)
            quote = fetch_live_quote(
                client, config.DB_PATH,
                symbol=symbol, epic=pcfg["epic"],
                pip_size=pcfg["pip_size"],
            )
            if quote is None:
                log.warning("[%s] Quote fetch failed — skipping", symbol)
                continue

            # 2. Session gate
            if not in_session:
                continue

            # 3. Spread filter
            if not spread_filt.acceptable(quote["spread_pips"]):
                log.info("[%s] Spread %.1f pips — too wide, skipping", symbol, quote["spread_pips"])
                continue

            # 4. Skip if already in a position for this pair
            if db.open_trade(config.DB_PATH, symbol):
                continue

            # 5. Load cached bars and run strategy
            bars = db.load_ohlc(config.DB_PATH, symbol, "HOUR", limit=200)
            if len(bars) < 50:
                log.warning("[%s] Only %d cached bars — need at least 50", symbol, len(bars))
                continue

            signal_data = mean_reversion.generate(bars)
            if signal_data:
                signal_data["symbol"]        = symbol
                signal_data["epic"]          = pcfg["epic"]
                signal_data["currency"]      = pcfg["currency"]
                signal_data["pip_size"]      = pcfg["pip_size"]
                signal_data["pip_value_usd"] = pcfg["pip_value_usd"]

                # Recalculate entry/stop/target from live quote so levels
                # are valid at fill time (OHLC close may be stale)
                atr = signal_data["atr"]
                if signal_data["direction"] == "long":
                    live_entry = quote["ask"]
                    signal_data["entry"]  = round(live_entry, 5)
                    signal_data["stop"]   = round(live_entry - 0.8 * atr, 5)
                    signal_data["target"] = round(live_entry + 1.6 * atr, 5)
                else:
                    live_entry = quote["bid"]
                    signal_data["entry"]  = round(live_entry, 5)
                    signal_data["stop"]   = round(live_entry + 0.8 * atr, 5)
                    signal_data["target"] = round(live_entry - 1.6 * atr, 5)

                signal_id               = db.insert_signal(config.DB_PATH, signal_data)
                signal_data["id"]       = signal_id
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
