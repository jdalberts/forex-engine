"""SQLite database — schema, connection helper, and all query functions."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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

            CREATE TABLE IF NOT EXISTS trailing_state (
                symbol     TEXT PRIMARY KEY,
                best_price REAL NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cot_data (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                net_spec    REAL NOT NULL,
                net_comm    REAL NOT NULL,
                UNIQUE(report_date, symbol)
            );

            CREATE INDEX IF NOT EXISTS idx_ohlc_symbol_time
                ON ohlc(symbol, timeframe, time);
            CREATE INDEX IF NOT EXISTS idx_quotes_symbol_time
                ON quotes(symbol, time);
            CREATE INDEX IF NOT EXISTS idx_cot_symbol_date
                ON cot_data(symbol, report_date);
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
                "open", trade.get("opened_at", datetime.now(timezone.utc).replace(tzinfo=None).isoformat()),
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


def all_open_trades(path: str) -> list[dict]:
    """[NEW — Step 7A] All currently open trades across every symbol (for correlation check)."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT symbol, direction, opened_at FROM trades WHERE status='open' ORDER BY opened_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def close_trade(path: str, trade_id: int, exit_price: float, pnl: float) -> None:
    with connect(path) as conn:
        conn.execute(
            "UPDATE trades SET exit_price=?, pnl=?, status='closed', closed_at=? WHERE id=?",
            (exit_price, pnl, datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), trade_id),
        )


def get_signal(path: str, signal_id: int) -> dict | None:
    """[NEW — Step 5] Fetch a single signal row by ID (used to check strategy type)."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM signals WHERE id=?", (signal_id,)
        ).fetchone()
    return dict(row) if row else None


def daily_pnl(path: str) -> float:
    """[NEW — Step 5] Sum of P&L from trades closed today (UTC date). Negative = loss."""
    today = datetime.now(timezone.utc).date().isoformat()
    with connect(path) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0.0) FROM trades "
            "WHERE status='closed' AND DATE(closed_at) = ?",
            (today,),
        ).fetchone()
    return float(row[0]) if row else 0.0


def update_trade_stop(path: str, trade_id: int, new_stop: float) -> None:
    """[NEW — Step 5] Persist updated stop level after a trailing stop moves."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE trades SET stop_level=? WHERE id=?",
            (new_stop, trade_id),
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
            (balance, datetime.now(timezone.utc).replace(tzinfo=None).isoformat()),
        )


# ── Trailing stop persistence [NEW — Step 9] ──────────────────────────────────

def save_trailing_best(path: str, symbol: str, best_price: float) -> None:
    """Upsert the best-price tracker for a symbol."""
    ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO trailing_state(symbol, best_price, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET best_price=excluded.best_price, updated_at=excluded.updated_at",
            (symbol, best_price, ts),
        )


def load_trailing_best(path: str) -> dict[str, float]:
    """Load all persisted best-price entries → {symbol: best_price}."""
    with connect(path) as conn:
        rows = conn.execute("SELECT symbol, best_price FROM trailing_state").fetchall()
    return {r["symbol"]: float(r["best_price"]) for r in rows}


def delete_trailing_best(path: str, symbol: str) -> None:
    """Remove a symbol's trailing state (called when position closes)."""
    with connect(path) as conn:
        conn.execute("DELETE FROM trailing_state WHERE symbol=?", (symbol,))


# ── Maintenance [NEW — Step 9] ─────────────────────────────────────────────────

def prune_old_records(path: str, days: int = 90) -> None:
    """Delete quotes older than `days` days.  Trades and equity are kept forever."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None).isoformat()
    with connect(path) as conn:
        deleted = conn.execute(
            "DELETE FROM quotes WHERE time < ?", (cutoff,)
        ).rowcount
    if deleted:
        import logging as _log
        _log.getLogger(__name__).info("Pruned %d quote records older than %d days", deleted, days)


def equity_history(path: str, limit: int = 200) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT balance, recorded_at FROM equity ORDER BY recorded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── COT data [NEW — Step 10] ───────────────────────────────────────────────────

def save_cot(path: str, rows: list[dict]) -> int:
    """Upsert COT rows. Each row: {report_date, symbol, net_spec, net_comm}.
    Returns number of rows inserted (ignored = already existed)."""
    data = [
        (r["report_date"], r["symbol"], r["net_spec"], r["net_comm"])
        for r in rows
    ]
    with connect(path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO cot_data(report_date, symbol, net_spec, net_comm) "
            "VALUES (?,?,?,?)",
            data,
        )
    return len(data)


def load_cot_history(path: str, symbol: str, weeks: int = 52) -> list[dict]:
    """Return last `weeks` COT rows for symbol, oldest-first."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT report_date, symbol, net_spec, net_comm FROM cot_data "
            "WHERE symbol=? ORDER BY report_date DESC LIMIT ?",
            (symbol, weeks),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def latest_cot_date(path: str, symbol: str) -> str | None:
    """Return the most recent report_date stored for symbol."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT MAX(report_date) FROM cot_data WHERE symbol=?", (symbol,)
        ).fetchone()
    return row[0] if row else None
