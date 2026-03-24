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
import pathlib
import signal as _signal
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import pandas as pd                                                      # [NEW — Step 8] moved from inside loop

from core import config, db
from core.ig_client import IGClient
from data.cot_fetcher import refresh_cot, seed_cot                      # [NEW — Step 10]
from data.fetcher import fetch_live_quote, refresh_bars, seed_history   # [NEW — Step 8]
from data.news_filter import is_news_window, refresh_news_cache         # [NEW — Step 11]
from execution.gateway import ExecutionGateway
from risk.guard import (CorrelationGuard, DailyLossGuard, EquityGuard,    # [NEW — Step 7A]
                        PositionSizer, SessionGate, SpreadFilter,         # [NEW — Step 5]
                        TrailingStopManager)                              # [NEW — Step 5]
from strategy import mean_reversion
from strategy.cot_bias import CotBias                               # [NEW — Step 10]
from strategy.mtf_filter import confirm_entry                       # [NEW — Step 7B]
from strategy.regime_detection import detect_market_regime          # [NEW — Step 4]
from strategy.trend_following import trend_following_signal         # [NEW — Step 4]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# [NEW — Step 9] File logging with rotation — survives background/service runs
pathlib.Path(config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
_fh = RotatingFileHandler(config.LOG_FILE,
                           maxBytes=config.LOG_MAX_BYTES,
                           backupCount=config.LOG_BACKUP_COUNT)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logging.getLogger().addHandler(_fh)

log = logging.getLogger("engine")


def _alert(msg: str) -> None:
    """[NEW — Step 9] Append a timestamped line to the alert log for critical events."""
    pathlib.Path(config.ALERT_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(config.ALERT_FILE, "a") as _f:
        _f.write(f"{datetime.now(timezone.utc).isoformat()} ALERT: {msg}\n")
    log.warning("ALERT: %s", msg)

_running = True


# [NEW — Step 4] Strategy switcher ────────────────────────────────────────────
def select_strategy(regime: str, bars: list[dict]):
    """
    Route to the correct strategy function based on market regime.

    "ranging"         → mean reversion  (existing)
    "trending"        → trend following (new)
    "high_volatility" → no trade        (pause)

    Returns a signal dict or None.
    """
    if regime == "ranging":
        return mean_reversion.generate(bars)       # [EXISTING]
    elif regime == "trending":
        return trend_following_signal(bars)        # [NEW — Step 4]
    else:  # "high_volatility"
        log.info("[switcher] High volatility regime — skipping trade")
        return None


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
    db.prune_old_records(config.DB_PATH, config.DB_PRUNE_DAYS)             # [NEW — Step 9]
    seed_cot(config.DB_PATH)                                               # [NEW — Step 10]

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
        _alert("IG authentication failed on startup — engine did not start")   # [NEW — Step 9]
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
        seed_history(client, config.DB_PATH, symbol=symbol, epic=pcfg["epic"],
                     price_scale=pcfg.get("price_scale", 1))
        if config.MTF_ENABLED:                                              # [NEW — Step 7B]
            seed_history(client, config.DB_PATH, symbol=symbol, epic=pcfg["epic"],
                         price_scale=pcfg.get("price_scale", 1),
                         resolution=config.MTF_RESOLUTION)

    # ── Fetch real account balance from IG ────────────────────────────────────
    real_balance = client.get_account_balance()
    if real_balance is not None:
        log.info("IG account balance: $%.2f", real_balance)
    else:
        real_balance = config.INITIAL_BALANCE
        log.warning("Could not fetch IG balance — using config.INITIAL_BALANCE ($%.2f)", real_balance)

    # ── Risk ──────────────────────────────────────────────────────────────────
    session      = SessionGate()
    spread_filt  = SpreadFilter()
    equity_guard = EquityGuard(config.DB_PATH, initial_balance=real_balance)
    sizer        = PositionSizer()
    daily_guard  = DailyLossGuard(config.DB_PATH, real_balance)            # [NEW — Step 5]
    trailing     = TrailingStopManager(db_path=config.DB_PATH)              # [NEW — Step 9] persist _best
    corr_guard   = CorrelationGuard()                                       # [NEW — Step 7A]
    cot_filter   = CotBias(db_path=config.DB_PATH)                         # [NEW — Step 10]

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

    _last_ohlc_refresh  = 0.0   # [NEW — Step 8] monotonic timestamps for rate-limited tasks
    _last_position_sync = 0.0   # [NEW — Step 8]
    _last_cot_refresh   = 0.0   # [NEW — Step 10]
    _last_news_refresh  = 0.0   # [NEW — Step 11]

    # ── Main loop ─────────────────────────────────────────────────────────────
    while _running:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        in_session = session.is_open(now)

        # Refresh real balance from IG each loop so risk controls stay accurate
        live_balance = client.get_account_balance()
        if live_balance is not None:
            _was_halted = equity_guard.halted
            equity_guard.update(live_balance)
            daily_guard.update_balance(live_balance)
            if equity_guard.halted and not _was_halted:                    # [NEW — Step 9]
                _alert(f"HARD DRAWDOWN halt triggered — balance ${live_balance:.2f}")

        _now_mono = time.monotonic()                                         # [NEW — Step 8]

        # [NEW — Step 8] Incremental OHLC refresh — keeps strategy bars current
        if _now_mono - _last_ohlc_refresh >= config.OHLC_REFRESH_INTERVAL_SEC:
            for _sym, _pcfg in pairs.items():
                refresh_bars(client, config.DB_PATH, _sym, _pcfg["epic"],
                             price_scale=_pcfg.get("price_scale", 1), resolution="HOUR")
                if config.MTF_ENABLED:
                    refresh_bars(client, config.DB_PATH, _sym, _pcfg["epic"],
                                 price_scale=_pcfg.get("price_scale", 1),
                                 resolution=config.MTF_RESOLUTION)
            _last_ohlc_refresh = _now_mono

        # [NEW — Step 10] Hourly COT refresh — picks up new weekly report
        if _now_mono - _last_cot_refresh >= config.COT_REFRESH_INTERVAL_SEC:
            refresh_cot(config.DB_PATH)
            _last_cot_refresh = _now_mono

        # [NEW — Step 11] Hourly news cache refresh — keeps upcoming event list current
        if _now_mono - _last_news_refresh >= config.COT_REFRESH_INTERVAL_SEC:
            refresh_news_cache(now)
            _last_news_refresh = _now_mono

        # [NEW — Step 8] Mid-session position sync — detect positions IG closed
        if _now_mono - _last_position_sync >= config.POSITION_SYNC_INTERVAL_SEC:
            _ig_open = {p["market"]["epic"] for p in client.get_open_positions()}
            for _sym, _pcfg in pairs.items():
                _db_trade = db.open_trade(config.DB_PATH, _sym)
                if _db_trade and _pcfg["epic"] not in _ig_open:
                    _quote = db.latest_quote(config.DB_PATH, _sym)
                    if _quote:
                        _mid   = (float(_quote["bid"]) + float(_quote["ask"])) / 2
                        _entry = float(_db_trade["entry_price"])
                        _size  = float(_db_trade["size"])
                        _pnl   = round(
                            (_mid - _entry) * _size if _db_trade["direction"] == "long"
                            else (_entry - _mid) * _size, 2
                        )
                    else:
                        _mid, _pnl = float(_db_trade.get("entry_price", 0)), 0.0
                    db.close_trade(config.DB_PATH, _db_trade["id"],
                                   exit_price=_mid, pnl=_pnl)
                    log.info("[%s] Mid-session sync: IG closed position — DB updated  pnl=%.2f",
                             _sym, _pnl)
            _last_position_sync = _now_mono


        for symbol, pcfg in pairs.items():
            time.sleep(config.ENGINE_STAGGER_SEC)   # stagger API calls — avoids IG rate limit burst

            # 1. Fetch live quote (always — keeps dashboard fresh)
            quote = fetch_live_quote(
                client, config.DB_PATH,
                symbol=symbol, epic=pcfg["epic"],
                pip_size=pcfg["pip_size"],
                price_scale=pcfg.get("price_scale", 1),
            )
            if quote is None:
                log.warning("[%s] Quote fetch failed — skipping", symbol)
                continue

            # 2. Session gate
            if not in_session:
                continue

            # 2b. [NEW — Step 11] News filter — pause during high-impact releases
            if config.NEWS_FILTER_ENABLED and is_news_window(now):
                log.info("[%s] News window active — skipping signal", symbol)
                continue

            # 3. Spread filter
            if not spread_filt.acceptable(quote["spread_pips"]):
                log.info("[%s] Spread %.1f pips — too wide, skipping", symbol, quote["spread_pips"])
                continue

            # 4. [NEW — Step 5] Daily loss limit — pause all new trades for today
            if not daily_guard.allow_trade():
                log.info("[%s] Daily loss limit active — skipping", symbol)
                continue

            # 5. [NEW — Step 5] Trailing stop — update open trending positions
            open_trade_row = db.open_trade(config.DB_PATH, symbol)
            if open_trade_row:
                sig_row = db.get_signal(config.DB_PATH, open_trade_row["signal_id"])
                if sig_row and sig_row.get("strategy") == "trend_following":
                    bars_atr = db.load_ohlc(config.DB_PATH, symbol, "HOUR", limit=config.ENGINE_TRAILING_BARS)
                    if len(bars_atr) >= config.ENGINE_TRAILING_ATR_PERIOD:
                        _df  = pd.DataFrame(bars_atr)
                        _hl  = _df["high"] - _df["low"]
                        _hc  = (_df["high"] - _df["close"].shift()).abs()
                        _lc  = (_df["low"]  - _df["close"].shift()).abs()
                        _atr = float(pd.concat([_hl, _hc, _lc], axis=1).max(axis=1).rolling(config.ENGINE_TRAILING_ATR_PERIOD).mean().iloc[-1])
                        _price = quote["ask"] if open_trade_row["direction"] == "long" else quote["bid"]
                        new_stop = trailing.update(
                            symbol, open_trade_row["direction"],
                            _price, float(open_trade_row["stop_level"]), _atr,
                        )
                        if new_stop:
                            db.update_trade_stop(config.DB_PATH, open_trade_row["id"], new_stop)
                            if not dry_run:
                                client.amend_stop(pcfg["epic"], new_stop,
                                                  price_scale=pcfg.get("price_scale", 1))   # [B6 FIX — Step 11]
                continue   # position already open — skip strategy signal

            # 7. Load cached bars and run strategy
            bars = db.load_ohlc(config.DB_PATH, symbol, "HOUR", limit=config.ENGINE_STRATEGY_BARS)
            if len(bars) < config.ENGINE_STRATEGY_MIN_BARS:
                log.warning("[%s] Only %d cached bars — need at least %d", symbol, len(bars), config.ENGINE_STRATEGY_MIN_BARS)
                continue

            regime      = detect_market_regime(bars)            # [NEW — Step 4]
            signal_data = select_strategy(regime, bars)        # [NEW — Step 4]

            # [NEW — Step 7A] Correlation guard — block if same USD-direction group is occupied
            if signal_data:
                all_open = db.all_open_trades(config.DB_PATH)
                if not corr_guard.allow_trade(symbol, signal_data["direction"], all_open):
                    log.info("[%s] Correlation limit — skipping %s signal",
                             symbol, signal_data["direction"])
                    signal_data = None

            # [NEW — Step 7B] Multi-timeframe entry confirmation
            if signal_data and config.MTF_ENABLED:
                bars_5m = db.load_ohlc(config.DB_PATH, symbol,
                                       config.MTF_RESOLUTION, limit=config.MTF_BARS)
                if not confirm_entry(signal_data, bars_5m):
                    log.info("[%s] 5m filter rejected %s signal",
                             symbol, signal_data["direction"])
                    signal_data = None

            # [NEW — Step 10] COT bias gate — block signals against extreme spec positioning
            if signal_data and config.COT_ENABLED:
                _cot_bias = cot_filter.get_bias(symbol)
                if _cot_bias != "neutral" and _cot_bias != signal_data["direction"]:
                    log.info("[%s] COT bias is %s — blocking %s signal",
                             symbol, _cot_bias, signal_data["direction"])
                    signal_data = None

            if signal_data:
                signal_data["symbol"]        = symbol
                signal_data["epic"]          = pcfg["epic"]
                signal_data["currency"]      = pcfg["currency"]
                signal_data["pip_size"]      = pcfg["pip_size"]
                signal_data["pip_value_usd"] = pcfg["pip_value_usd"]

                # Recalculate entry/stop/target from live quote so levels
                # are valid at fill time (OHLC close may be stale).
                # Use the strategy's own distances (not hardcoded multipliers)
                # so this block works correctly for any strategy.
                stop_dist   = abs(signal_data["entry"] - signal_data["stop"])
                target_dist = abs(signal_data["target"] - signal_data["entry"])

                if signal_data["direction"] == "long":
                    live_entry = quote["ask"]
                    signal_data["entry"]  = round(live_entry, 5)
                    signal_data["stop"]   = round(live_entry - stop_dist, 5)
                    signal_data["target"] = round(live_entry + target_dist, 5)
                else:
                    live_entry = quote["bid"]
                    signal_data["entry"]  = round(live_entry, 5)
                    signal_data["stop"]   = round(live_entry + stop_dist, 5)
                    signal_data["target"] = round(live_entry - target_dist, 5)

                # Enforce IG minimum stop distance — IG rejects orders where
                # stop is closer than their instrument minimum.
                min_stop_pips = quote.get("min_stop_pips", 0)
                if min_stop_pips > 0:
                    pip_size         = pcfg["pip_size"]
                    stop_pips        = abs(signal_data["entry"] - signal_data["stop"]) / pip_size
                    if stop_pips < min_stop_pips:
                        min_dist = min_stop_pips * pip_size * config.MIN_STOP_BUFFER
                        if signal_data["direction"] == "long":
                            signal_data["stop"]   = round(signal_data["entry"] - min_dist, 5)
                            signal_data["target"] = round(signal_data["entry"] + min_dist * 2, 5)
                        else:
                            signal_data["stop"]   = round(signal_data["entry"] + min_dist, 5)
                            signal_data["target"] = round(signal_data["entry"] - min_dist * 2, 5)
                        log.info(
                            "[%s] Stop widened to meet IG minimum: %.1f pips → %.1f pips",
                            symbol, stop_pips, min_stop_pips * config.MIN_STOP_BUFFER,
                        )

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
