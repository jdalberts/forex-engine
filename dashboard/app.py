"""Dashboard — FastAPI backend serving live state from SQLite."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import config, db

app = FastAPI(title="Forex Engine Dashboard", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/state")
def state():
    """Single endpoint — returns everything the UI needs."""
    db_path = config.DB_PATH

    quote    = db.latest_quote(db_path, config.SYMBOL)
    position = db.open_trade(db_path, config.SYMBOL)
    signals  = db.recent_signals(db_path, limit=10)
    trades   = db.recent_trades(db_path, limit=10)
    equity   = db.equity_history(db_path, limit=100)

    # Derive spread_pips from latest quote
    spread_pips = None
    if quote:
        try:
            spread_pips = round(
                (float(quote["ask"]) - float(quote["bid"])) / config.PIP_SIZE, 1
            )
        except Exception:
            pass

    # Derive live PnL for open position
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

    return JSONResponse({
        "symbol":      config.SYMBOL,
        "quote":       dict(quote) if quote else None,
        "spread_pips": spread_pips,
        "position":    dict(position) if position else None,
        "live_pnl":    live_pnl,
        "signals":     signals,
        "trades":      trades,
        "equity":      equity,
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "dashboard.app:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
    )
