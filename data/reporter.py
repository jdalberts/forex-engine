"""
[NEW — Step 14] Daily performance report builder.

Generates a Telegram-formatted end-of-session summary covering:
  - Trades taken today (wins / losses)
  - Today's P&L
  - Running account balance and drawdown
  - All-time aggregate stats

Called once per day at/after session close (16:00 UTC).
"""

from __future__ import annotations

from datetime import datetime, timezone

from core import config, db


def build_daily_report(
    db_path:      str,
    balance:      float,
    peak_balance: float | None = None,
) -> str:
    """
    Build and return a Telegram-formatted daily summary string.

    Parameters
    ----------
    db_path      : path to the SQLite database
    balance      : current account balance (from EquityGuard or broker API)
    peak_balance : high-water-mark balance for drawdown calculation.
                   Defaults to `balance` (0% drawdown) if not supplied, so
                   adding/withdrawing demo capital never produces a phantom DD.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    peak  = peak_balance if peak_balance and peak_balance > 0 else balance

    # ── Today's trades ────────────────────────────────────────────────────────
    trades    = db.today_closed_trades(db_path)
    n_trades  = len(trades)
    wins      = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
    losses    = n_trades - wins
    today_pnl = db.daily_pnl(db_path)

    # ── All-time stats ────────────────────────────────────────────────────────
    stats = db.all_time_stats(db_path)

    # ── Drawdown ──────────────────────────────────────────────────────────────
    drawdown_pct = max(0.0, round((1.0 - balance / peak) * 100, 1))

    # ── Format ────────────────────────────────────────────────────────────────
    pnl_sign    = "+" if today_pnl >= 0 else ""
    at_sign     = "+" if stats["total_pnl"] >= 0 else ""
    session_str = (f"{config.SESSION_START_UTC.strftime('%H:%M')}–"
                   f"{config.SESSION_END_UTC.strftime('%H:%M')} UTC")

    lines = [
        f"📊 DAILY REPORT — {today}",
        f"Session: {session_str}",
        "",
        f"Trades Today: {n_trades}",
    ]

    if n_trades > 0:
        win_rate_today = round(wins / n_trades * 100, 1)
        lines += [
            f"  ✅ {wins} wins  |  ❌ {losses} losses",
            f"Win Rate: {win_rate_today}%",
            f"Today's P&L: {pnl_sign}${today_pnl:.2f}",
        ]
    else:
        lines += [
            "  No trades taken today",
            f"Today's P&L: $0.00",
        ]

    lines += [
        "",
        f"Balance: ${balance:,.2f}",
        f"Drawdown: {drawdown_pct}%",
        "",
        (f"All-Time: {stats['total']} trades  |  "
         f"{stats['win_rate']}% win rate  |  "
         f"{at_sign}${stats['total_pnl']:.2f}"),
    ]

    return "\n".join(lines)
