"""Dashboard — FastAPI backend serving live state from SQLite."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import config, db
from data.news_filter import is_news_window, next_news_event, refresh_news_cache
from strategy.cot_bias import CotBias
from strategy.regime_detection import detect_market_regime

app = FastAPI(title="Forex Engine Dashboard", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_cot = CotBias(db_path=config.DB_PATH)


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


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
                if position["direction"] == "long":
                    live_pnl = round((mid - entry) * size, 2)
                else:
                    live_pnl = round((entry - mid) * size, 2)
            except Exception:
                pass

        regime = "unknown"
        try:
            bars = db.load_ohlc(db_path, symbol, timeframe="HOUR", limit=100)
            if len(bars) >= 40:
                regime = detect_market_regime(bars)
        except Exception:
            pass

        cot_bias = _cot.get_bias(symbol)

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
    })


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
