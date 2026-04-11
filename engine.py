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
import sqlite3
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import pandas as pd                                                      # [NEW — Step 8] moved from inside loop

from core import config, db
if config.BROKER == "mt5":
    from core.mt5_client import MT5Client
else:
    from core.ig_client import IGClient
from data.cot_fetcher import refresh_cot, seed_cot                      # [NEW — Step 10]
from data.fetcher import fetch_live_quote, refresh_bars, seed_history   # [NEW — Step 8]
from data.news_filter import (is_news_window, refresh_news_cache,        # [NEW — Step 11]
                              refresh_central_bank_calendar)
from data.notifier import send_alert                                     # [NEW — Step 13]
from data.reporter import build_daily_report                             # [NEW — Step 14]
from execution.gateway import ExecutionGateway
from risk.guard import (CorrelationGuard, DailyLossGuard, EquityGuard,    # [NEW — Step 7A]
                        PositionSizer, SessionGate, SpreadFilter,         # [NEW — Step 5]
                        TrailingStopManager)                              # [NEW — Step 5]
from strategy import mean_reversion
from data.sentiment import SentimentFilter, refresh_sentiment        # [NEW — AI sentiment]
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


# [NEW — Per-asset params] Apply/restore strategy parameters per instrument
import strategy.mean_reversion as _mr_mod
import strategy.trend_following as _tf_mod
import strategy.regime_detection as _rd_mod

_GLOBAL_PARAMS = None  # saved on first call


def _save_global_params():
    """Save global strategy params so we can restore after per-asset override."""
    global _GLOBAL_PARAMS
    if _GLOBAL_PARAMS is not None:
        return
    _GLOBAL_PARAMS = {
        "mr_rsi_oversold": _mr_mod.RSI_OVERSOLD,
        "mr_rsi_overbought": _mr_mod.RSI_OVERBOUGHT,
        "mr_stop_mult": _mr_mod.STOP_ATR_MULT,
        "mr_target_mult": _mr_mod.TARGET_ATR_MULT,
        "tf_fast_ema": _tf_mod.FAST_EMA_PERIOD,
        "tf_slow_ema": _tf_mod.SLOW_EMA_PERIOD,
        "tf_stop_mult": _tf_mod.STOP_ATR_MULT,
        "tf_target_mult": _tf_mod.TARGET_ATR_MULT,
        "adx_threshold": _rd_mod.ADX_TREND_THRESHOLD,
        "trail_atr": config.TRAILING_ATR_MULT,
    }


def _apply_params(params: dict):
    """Apply strategy params (either per-asset or global)."""
    _mr_mod.RSI_OVERSOLD = params["mr_rsi_oversold"]
    _mr_mod.RSI_OVERBOUGHT = params["mr_rsi_overbought"]
    _mr_mod.STOP_ATR_MULT = params["mr_stop_mult"]
    _mr_mod.TARGET_ATR_MULT = params["mr_target_mult"]
    _tf_mod.FAST_EMA_PERIOD = params["tf_fast_ema"]
    _tf_mod.SLOW_EMA_PERIOD = params["tf_slow_ema"]
    _tf_mod.STOP_ATR_MULT = params["tf_stop_mult"]
    _tf_mod.TARGET_ATR_MULT = params["tf_target_mult"]
    _rd_mod.ADX_TREND_THRESHOLD = params["adx_threshold"]


def _restore_global_params():
    """Restore global params after per-asset override."""
    if _GLOBAL_PARAMS:
        _apply_params(_GLOBAL_PARAMS)


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

    # When using MT5, swap epic → mt5_symbol and force price_scale=1
    # so the rest of the engine works unchanged.
    if config.BROKER == "mt5":
        for _k, _v in pairs.items():
            _v["epic"] = _v.get("mt5_symbol", _k)
            _v["price_scale"] = 1

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
    refresh_central_bank_calendar()                                        # [NEW — Step 11] seed news_events.json

    # ── Broker client ──────────────────────────────────────────────────────────
    if config.BROKER == "mt5":
        client = MT5Client(
            login    = config.MT5_LOGIN,
            password = config.MT5_PASSWORD,
            server   = config.MT5_SERVER,
            path     = config.MT5_PATH,
        )
    else:
        client = IGClient(
            api_key    = config.IG_API_KEY,
            identifier = config.IG_IDENTIFIER,
            password   = config.IG_PASSWORD,
            account_id = config.IG_ACCOUNT_ID,
            demo       = config.IG_DEMO,
        )
    if not client.authenticate():
        log.error("Broker authentication failed — check .env credentials")
        _alert("Broker authentication failed on startup — engine did not start")
        send_alert(
            "🚨 ENGINE ALERT\n"
            "Broker authentication failed — engine did not start\n"
            "Check .env credentials"
        )
        return

    # ── Sync: close DB trades that IG already closed ──────────────────────────
    try:                                                                     # [BUG 4 FIX]
        ig_open = {p["market"]["epic"] for p in client.get_open_positions()}
    except (KeyError, TypeError, ConnectionError, OSError) as exc:
        log.warning("Startup sync: failed to fetch broker positions — %s", exc)
        ig_open = None
    if ig_open is not None:
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
                try:                                                         # [BUG 4 FIX]
                    db.close_trade(config.DB_PATH, db_trade["id"],
                                   exit_price=mid if quote else entry, pnl=pnl)
                    log.info("[%s] Position closed by broker — synced DB  estimated_pnl=%.2f", symbol, pnl)
                except (KeyError, TypeError, sqlite3.Error) as exc:
                    log.warning("[%s] Startup sync: DB close failed — %s", symbol, exc)

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
        log.info("Account balance: $%.2f", real_balance)
    else:
        real_balance = config.INITIAL_BALANCE
        log.warning("Could not fetch balance — using config.INITIAL_BALANCE ($%.2f)", real_balance)

    # ── Risk ──────────────────────────────────────────────────────────────────
    session      = SessionGate()
    spread_filt  = SpreadFilter()
    equity_guard = EquityGuard(config.DB_PATH, initial_balance=real_balance)
    sizer        = PositionSizer()
    daily_guard  = DailyLossGuard(config.DB_PATH, real_balance)            # [NEW — Step 5]
    trailing     = TrailingStopManager(db_path=config.DB_PATH)              # [NEW — Step 9] persist _best
    corr_guard   = CorrelationGuard()                                       # [NEW — Step 7A]
    cot_filter   = CotBias(db_path=config.DB_PATH)                         # [NEW — Step 10]
    sent_filter  = SentimentFilter()                                         # [NEW — AI sentiment]

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

    send_alert(                                                             # [NEW — Step 18]
        f"✅ ENGINE STARTED\n"
        f"Pairs: {', '.join(pairs)}\n"
        f"Mode: {'DRY RUN' if dry_run else 'LIVE'}\n"
        f"Session: 14:00–18:00 SAST\n"
        f"Balance: ${real_balance:,.2f}"
    )

    _last_ohlc_refresh  = 0.0              # [NEW — Step 8] monotonic timestamps for rate-limited tasks
    _last_position_sync = 0.0              # [NEW — Step 8]
    _last_cot_refresh   = time.monotonic() # [NEW — Step 10] seed already ran; don't re-download immediately
    _last_news_refresh  = 0.0              # [NEW — Step 11]
    _daily_loss_alerted: set = set()       # [NEW — Step 13] dates already alerted to avoid repeat spam
    _last_report_date:   str = ""          # [NEW — Step 14] date of last daily report sent

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
                send_alert(                                                 # [NEW — Step 13]
                    f"🚨 HARD DRAWDOWN HALT\n"
                    f"Balance: ${live_balance:.2f}\n"
                    f"All trading suspended — manual review required"
                )

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

        # [NEW — AI sentiment] Refresh headline sentiment every 15 min during session
        if in_session:
            refresh_sentiment()

        # [NEW — Step 8] Mid-session position sync — detect positions IG closed
        if _now_mono - _last_position_sync >= config.POSITION_SYNC_INTERVAL_SEC:
            try:                                                             # [BUG 4 FIX]
                _ig_open = {p["market"]["epic"] for p in client.get_open_positions()}
            except (KeyError, TypeError, ConnectionError, OSError) as exc:
                log.warning("Position sync: failed to fetch broker positions — %s", exc)
                _ig_open = None
            if _ig_open is not None:
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
                        try:                                                 # [BUG 4 FIX]
                            db.close_trade(config.DB_PATH, _db_trade["id"],
                                           exit_price=_mid, pnl=_pnl)
                        except (KeyError, TypeError, sqlite3.Error) as exc:
                            log.warning("[%s] Position sync: DB close failed — %s",
                                        _sym, exc)
                            continue
                        log.info("[%s] Mid-session sync: Broker closed position — DB updated  pnl=%.2f",
                                 _sym, _pnl)
                        send_alert(                                         # [NEW — Step 13]
                            f"🔴 TRADE CLOSED\n"
                            f"{_sym}  |  est. P&L: ${_pnl:+.2f}"
                        )
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

            # 2b. Dashboard pause check — skip trading but keep quotes flowing
            _pause_file = pathlib.Path(config.DB_PATH).parent / ".engine_paused"
            if _pause_file.exists():
                if symbol == list(pairs.keys())[0]:  # log once per cycle
                    log.info("Engine PAUSED via dashboard — skipping all signals")
                continue

            # 2b. [NEW — Step 11] News filter — pause during high-impact releases
            if config.NEWS_FILTER_ENABLED and is_news_window(now):
                log.info("[%s] News window active — skipping signal", symbol)
                continue

            # 3. Spread filter (per-pair limit if configured, else global)
            _max_spread = pcfg.get("max_spread_pips", config.MAX_SPREAD_PIPS)
            if quote["spread_pips"] > _max_spread:
                log.info("[%s] Spread %.1f pips > %.1f limit — too wide, skipping",
                         symbol, quote["spread_pips"], _max_spread)
                continue

            # 4. [NEW — Step 5] Daily loss limit — pause all new trades for today
            if not daily_guard.allow_trade():
                _today_str = now.strftime("%Y-%m-%d")           # [NEW — Step 13]
                if _today_str not in _daily_loss_alerted:       # [NEW — Step 13] alert once per day
                    _dpnl = db.daily_pnl(config.DB_PATH)
                    send_alert(
                        f"⚠️ DAILY LOSS LIMIT\n"
                        f"Today's P&L: ${_dpnl:.2f}\n"
                        f"No new trades until tomorrow UTC"
                    )
                    _daily_loss_alerted.add(_today_str)
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

            # [NEW — Per-asset params] Apply asset-specific strategy params if configured
            _save_global_params()
            asset_params = pcfg.get("strategy_params")
            if asset_params:
                _apply_params(asset_params)

            regime      = detect_market_regime(bars)            # [NEW — Step 4]
            signal_data = select_strategy(regime, bars)        # [NEW — Step 4]

            # Restore global params after strategy evaluation
            if asset_params:
                _restore_global_params()

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

            # [NEW — AI sentiment] Block signals against strong headline sentiment
            if signal_data:
                if not sent_filter.allow_trade(symbol, signal_data["direction"]):
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
                _trade_id = gateway.submit(signal_data)
                if _trade_id:                                               # [NEW — Step 13]
                    _sp = round(abs(signal_data["entry"] - signal_data["stop"])   / signal_data["pip_size"])
                    _tp = round(abs(signal_data["target"] - signal_data["entry"]) / signal_data["pip_size"])
                    send_alert(
                        f"🟢 TRADE OPEN\n"
                        f"{symbol} {signal_data['direction'].upper()}\n"
                        f"Entry: {signal_data['entry']:.5f}  |  "
                        f"Stop: {signal_data['stop']:.5f}  |  "
                        f"Target: {signal_data['target']:.5f}\n"
                        f"Stop: {_sp}p  |  Target: {_tp}p"
                    )

        # [NEW — Step 14] Daily report — fire once after session closes each day
        if (not in_session
                and now.time() >= config.SESSION_END_UTC
                and now.strftime("%Y-%m-%d") != _last_report_date):
            _report = build_daily_report(
                config.DB_PATH,
                equity_guard.current_balance,
                peak_balance=equity_guard.peak_balance,
            )
            send_alert(_report)
            log.info("Daily report sent for %s", now.strftime("%Y-%m-%d"))
            _last_report_date = now.strftime("%Y-%m-%d")

        time.sleep(config.QUOTE_INTERVAL_SEC)

    log.info("Engine stopped.")
    if config.BROKER == "mt5":
        client.shutdown()
    send_alert("🛑 Engine stopped (normal shutdown)")                      # [NEW — Step 13]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Forex Engine")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Submit real orders (default: dry run)",
    )
    args = parser.parse_args()
    try:                                                                    # [NEW — Step 13]
        run(dry_run=not args.live)
    except Exception as _exc:                                              # [NEW — Step 13]
        log.exception("Engine crashed: %s", _exc)
        _alert(f"Engine crashed: {_exc}")
        send_alert(
            f"🚨 ENGINE CRASHED\n"
            f"{type(_exc).__name__}: {_exc}\n"
            f"Engine has stopped — restart required"
        )
        raise
