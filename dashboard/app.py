"""Dashboard — FastAPI backend serving live state from SQLite."""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import config, db
from data.news_filter import is_news_window, next_news_event, refresh_news_cache
from strategy.cot_bias import CotBias
from strategy.regime_detection import detect_market_regime

log = logging.getLogger(__name__)

app = FastAPI(title="Forex Engine Dashboard", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_cot = CotBias(db_path=config.DB_PATH)

# Pause file — engine checks this to decide whether to trade
PAUSE_FILE = Path(config.DB_PATH).parent / ".engine_paused"

# Backtest results cache — recomputed at most every 5 minutes
_bt_cache: dict | None = None
_bt_cache_ts: float = 0.0


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/backtest")
def backtest_page():
    return FileResponse(str(STATIC_DIR / "backtest.html"))


@app.get("/api/backtest")
def backtest_api():
    """Run baseline vs hybrid backtest on cached OHLC. Results cached 5 min."""
    global _bt_cache, _bt_cache_ts
    if _bt_cache is not None and _time.monotonic() - _bt_cache_ts < 300:
        return JSONResponse(_bt_cache)

    from backtest import compute_stats, run_backtest

    out: dict = {}
    for symbol, pcfg in config.PAIRS.items():
        bars = db.load_ohlc(config.DB_PATH, symbol, "HOUR", limit=5000)
        if len(bars) < 70:
            continue
        baseline = run_backtest(bars, pcfg, config.INITIAL_BALANCE, use_regime=False)
        hybrid   = run_backtest(bars, pcfg, config.INITIAL_BALANCE, use_regime=True)

        # Downsample equity curves (keep every 5th point) to reduce payload
        def _ds(curve):
            step = max(1, len(curve) // 200)
            return curve[::step]

        # Sanitise trades for JSON (convert numpy types, add bar-index as proxy time)
        def _clean_trades(trades, bars_list):
            out = []
            for t in trades:
                ei = int(t["entry_bar"])
                xi = int(t["exit_bar"])
                out.append({
                    "entry_time":  bars_list[min(ei, len(bars_list)-1)]["time"] if bars_list else "",
                    "exit_time":   bars_list[min(xi, len(bars_list)-1)]["time"] if bars_list else "",
                    "direction":   t["direction"],
                    "strategy":    t["strategy"],
                    "entry":       float(t["entry"]),
                    "exit_price":  float(t["exit_price"]),
                    "pnl":         float(t["pnl"]),
                    "result":      t["result"],
                    "contracts":   int(t["contracts"]),
                })
            return out

        out[symbol] = {
            "bars":      len(bars),
            "date_from": baseline["date_from"],
            "date_to":   baseline["date_to"],
            "baseline": {
                "stats":        compute_stats(baseline),
                "equity_curve": _ds(baseline["equity_curve"]),
                "trades":       _clean_trades(baseline["trades"], bars),
            },
            "hybrid": {
                "stats":        compute_stats(hybrid),
                "equity_curve": _ds(hybrid["equity_curve"]),
                "trades":       _clean_trades(hybrid["trades"], bars),
            },
        }

    _bt_cache    = out
    _bt_cache_ts = _time.monotonic()
    return JSONResponse(out)


@app.get("/api/state")
def state():
    """Single endpoint — returns everything the UI needs."""
    db_path = config.DB_PATH
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    refresh_news_cache(now)

    # ── Per-pair state ────────────────────────────────────────────────────────
    pairs_state = {}
    for symbol, pcfg in config.PAIRS.items():
        quote    = db.latest_quote(db_path, symbol)
        position = db.open_trade(db_path, symbol)

        spread_pips = None
        if quote:
            try:
                spread_pips = round(
                    (float(quote["ask"]) - float(quote["bid"])) / pcfg["pip_size"], 1
                )
            except Exception:
                pass

        live_pnl = None
        if position and quote:
            try:
                mid   = (float(quote["bid"]) + float(quote["ask"])) / 2
                entry = float(position["entry_price"])
                size  = float(position["size"])
                direction = position["direction"].lower()
                is_long = direction in ("long", "buy")
                if is_long:
                    live_pnl = round((mid - entry) * size, 2)
                else:
                    live_pnl = round((entry - mid) * size, 2)
            except (KeyError, TypeError, ValueError) as exc:
                log.debug("PnL calc failed for %s: %s", symbol, exc)

        regime = "unknown"
        try:
            bars = db.load_ohlc(db_path, symbol, timeframe="HOUR", limit=100)
            if len(bars) >= 40:
                regime = detect_market_regime(bars)
        except Exception as exc:
            log.warning("Regime detection failed for %s: %s", symbol, exc)

        try:
            cot_bias = _cot.get_bias(symbol)
        except Exception as exc:
            log.warning("COT bias failed for %s: %s", symbol, exc)
            cot_bias = "neutral"

        last_signal = None
        with db.connect(db_path) as conn:
            row = conn.execute(
                "SELECT strategy, direction, status, generated_at FROM signals "
                "WHERE symbol=? ORDER BY generated_at DESC LIMIT 1",
                (symbol,),
            ).fetchone()
            if row:
                last_signal = dict(row)

        pairs_state[symbol] = {
            "quote":       dict(quote) if quote else None,
            "spread_pips": spread_pips,
            "position":    dict(position) if position else None,
            "live_pnl":    live_pnl,
            "regime":      regime,
            "cot_bias":    cot_bias,
            "last_signal": last_signal,
        }

    # ── Global state ──────────────────────────────────────────────────────────
    signals = db.recent_signals(db_path, limit=20)
    trades  = db.recent_trades(db_path, limit=20)
    equity  = db.equity_history(db_path, limit=200)

    nxt = next_news_event(now)

    return JSONResponse({
        "pairs":        pairs_state,
        "signals":      signals,
        "trades":       trades,
        "equity":       equity,
        "trade_stats":  _trade_stats(db_path),
        "today_pnl":    db.daily_pnl(db_path),
        "news_active":  is_news_window(now),
        "next_event":   nxt.isoformat() if nxt else None,
        "engine_paused": PAUSE_FILE.exists(),
        "active_pairs":  list(config.PAIRS.keys()),
    })


@app.post("/api/engine/pause")
def pause_engine():
    """Create pause file — engine checks this each cycle and skips trading."""
    PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_FILE.write_text(datetime.now(timezone.utc).isoformat())
    log.warning("ENGINE PAUSED via dashboard")
    return JSONResponse({"status": "paused"})


@app.post("/api/engine/resume")
def resume_engine():
    """Remove pause file — engine resumes trading next cycle."""
    if PAUSE_FILE.exists():
        PAUSE_FILE.unlink()
    log.warning("ENGINE RESUMED via dashboard")
    return JSONResponse({"status": "running"})


def _trade_stats(db_path: str) -> dict:
    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pnl FROM trades WHERE status='closed' AND pnl IS NOT NULL"
        ).fetchall()
    if not rows:
        return {
            "total": 0, "wins": 0, "losses": 0,
            "win_rate": None, "avg_win": None, "avg_loss": None, "profit_factor": None,
        }
    pnls   = [float(r[0]) for r in rows]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))
    return {
        "total":         len(pnls),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(pnls) * 100, 1),
        "avg_win":       round(gross_profit / len(wins), 2) if wins else None,
        "avg_loss":      round(gross_loss / len(losses), 2) if losses else None,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "dashboard.app:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
    )
