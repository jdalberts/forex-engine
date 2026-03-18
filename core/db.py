"""SQLite database — schema, connection helper, and all query functions."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator


# ── Connection ────────────────────────────────────────────────────────────────

def init_db(path: str) -> None:
    """Create all tables and indexes if they don't exist."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ohlc (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol    TEXT    NOT NULL,
                timeframe TEXT    NOT NULL,
                time      TEXT    NOT NULL,
                open      REAL    NOT NULL,
                high      REAL    NOT NULL,
                low       REAL    NOT NULL,
                close     REAL    NOT NULL,
                volume    INTEGER DEFAULT 0,
                UNIQUE(symbol, timeframe, time)
            );

            CREATE TABLE IF NOT EXISTS quotes (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol  TEXT  NOT NULL,
                bid     REAL  NOT NULL,
                ask     REAL  NOT NULL,
                time    TEXT  NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT  NOT NULL,
                strategy     TEXT  NOT NULL,
                direction    TEXT  NOT NULL,
                entry        REAL  NOT NULL,
                stop         REAL  NOT NULL,
                target       REAL  NOT NULL,
                reason       TEXT,
                generated_at TEXT  NOT NULL,
                status       TEXT  DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS trades (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id    INTEGER,
                broker_ref   TEXT,
                symbol       TEXT  NOT NULL,
                direction    TEXT  NOT NULL,
                size         REAL  NOT NULL,
                entry_price  REAL,
                stop_level   REAL,
                limit_level  REAL,
                exit_price   REAL,
                pnl          REAL,
                status       TEXT  DEFAULT 'open',
                opened_at    TEXT,
                closed_at    TEXT,
                FOREIGN KEY(signal_id) REFERENCES signals(id)
            );

            CREATE TABLE IF NOT EXISTS equity (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                balance     REAL  NOT NULL,
                recorded_at TEXT  NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ohlc_symbol_time
                ON ohlc(symbol, timeframe, time);
            CREATE INDEX IF NOT EXISTS idx_quotes_symbol_time
                ON quotes(symbol, time);
        """)


@contextmanager
def connect(path: str) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── OHLC ──────────────────────────────────────────────────────────────────────

def upsert_ohlc(path: str, symbol: str, timeframe: str, bars: list[dict]) -> int:
    rows = [
        (symbol, timeframe, b["time"].isoformat(), b["open"], b["high"], b["low"], b["close"], b.get("volume", 0))
        for b in bars
    ]
    with connect(path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO ohlc(symbol, timeframe, time, open, high, low, close, volume) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def load_ohlc(path: str, symbol: str, timeframe: str = "HOUR", limit: int = 500) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT time, open, high, low, close, volume FROM ohlc "
            "WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT ?",
            (symbol, timeframe, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def latest_ohlc_time(path: str, symbol: str, timeframe: str) -> str | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT MAX(time) FROM ohlc WHERE symbol=? AND timeframe=?",
            (symbol, timeframe),
        ).fetchone()
    return row[0] if row else None


def count_ohlc(path: str, symbol: str, timeframe: str) -> int:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM ohlc WHERE symbol=? AND timeframe=?",
            (symbol, timeframe),
        ).fetchone()
    return row[0] if row else 0


# ── Quotes ────────────────────────────────────────────────────────────────────

def insert_quote(path: str, symbol: str, bid: float, ask: float, time: datetime) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO quotes(symbol, bid, ask, time) VALUES (?,?,?,?)",
            (symbol, bid, ask, time.isoformat()),
        )


def latest_quote(path: str, symbol: str) -> dict | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT bid, ask, time FROM quotes WHERE symbol=? ORDER BY time DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    return dict(row) if row else None


# ── Signals ───────────────────────────────────────────────────────────────────

def insert_signal(path: str, signal: dict) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO signals(symbol, strategy, direction, entry, stop, target, reason, generated_at, status) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                signal["symbol"], signal["strategy"], signal["direction"],
                signal["entry"], signal["stop"], signal["target"],
                signal.get("reason", ""), signal["generated_at"], "pending",
            ),
        )
    return cur.lastrowid


def update_signal_status(path: str, signal_id: int, status: str) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE signals SET status=? WHERE id=?", (status, signal_id))


def recent_signals(path: str, limit: int = 20) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM signals ORDER BY generated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Trades ────────────────────────────────────────────────────────────────────

def insert_trade(path: str, trade: dict) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO trades(signal_id, broker_ref, symbol, direction, size, "
            "entry_price, stop_level, limit_level, status, opened_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                trade.get("signal_id"), trade.get("broker_ref"),
                trade["symbol"], trade["direction"], trade["size"],
                trade.get("entry_price"), trade.get("stop_level"), trade.get("limit_level"),
                "open", trade.get("opened_at", datetime.utcnow().isoformat()),
            ),
        )
    return cur.lastrowid


def open_trade(path: str, symbol: str) -> dict | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM trades WHERE symbol=? AND status='open' ORDER BY opened_at DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    return dict(row) if row else None


def close_trade(path: str, trade_id: int, exit_price: float, pnl: float) -> None:
    with connect(path) as conn:
        conn.execute(
            "UPDATE trades SET exit_price=?, pnl=?, status='closed', closed_at=? WHERE id=?",
            (exit_price, pnl, datetime.utcnow().isoformat(), trade_id),
        )


def recent_trades(path: str, limit: int = 20) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY opened_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Equity ────────────────────────────────────────────────────────────────────

def record_equity(path: str, balance: float) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO equity(balance, recorded_at) VALUES (?,?)",
            (balance, datetime.utcnow().isoformat()),
        )


def equity_history(path: str, limit: int = 200) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT balance, recorded_at FROM equity ORDER BY recorded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]
