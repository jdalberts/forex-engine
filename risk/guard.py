"""Risk controls — session gate, spread filter, position sizing, drawdown guard."""

from __future__ import annotations

import logging
import math
from datetime import datetime, time as dtime, timezone
from typing import Optional

from core import config, db

log = logging.getLogger(__name__)


class SessionGate:
    """
    Allow trading only during the configured UTC window.
    Default: 12:00–16:00 UTC (London/NY overlap = 14:00–18:00 SAST).
    """

    def __init__(
        self,
        start_utc: dtime = config.SESSION_START_UTC,
        end_utc:   dtime = config.SESSION_END_UTC,
    ) -> None:
        self.start = start_utc
        self.end   = end_utc

    def is_open(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc).replace(tzinfo=None)
        return self.start <= now.time() < self.end and now.weekday() < 5  # [NEW — Step 8] no weekends

    def status(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc).replace(tzinfo=None)
        if self.is_open(now):
            return f"OPEN  {self.start:%H:%M}–{self.end:%H:%M} UTC"
        return f"CLOSED  next open {self.start:%H:%M} UTC"


class SpreadFilter:
    """Reject a quote when the spread is too wide."""

    def __init__(self, max_pips: float = config.MAX_SPREAD_PIPS) -> None:
        self.max_pips = max_pips

    def acceptable(self, spread_pips: float) -> bool:
        return spread_pips <= self.max_pips


class PositionSizer:
    """
    Calculate IG contract size so that a full stop-out costs exactly
    risk_fraction * balance * risk_scale.

    Formula: contracts = risk_amount / (stop_pips × pip_value_usd)
      where pip_value_usd = USD value per pip per 1 standard IG contract.
      EUR/USD: $10/pip | GBP/USD: $10/pip | USD/CHF: ~$12.50 | GBP/JPY: ~$6.30
    """

    def __init__(self, risk_fraction: float = config.RISK_PER_TRADE) -> None:
        self.risk_fraction = risk_fraction

    def lot_size(
        self,
        balance:        float,
        entry:          float,
        stop:           float,
        pip_size:       float = 0.0001,
        pip_value_usd:  float = 10.0,
        risk_scale:     float = 1.0,
    ) -> float:
        risk_amount   = balance * self.risk_fraction * risk_scale
        stop_distance = abs(entry - stop)
        if stop_distance <= 0:
            return 0.0
        stop_pips  = stop_distance / pip_size
        contracts  = risk_amount / (stop_pips * pip_value_usd)
        # IG minimum deal size is 1 contract; always round up to avoid
        # MINIMUM_ORDER_SIZE_ERROR (fractional sizes below 1 are rejected)
        contracts_ceiled = max(math.ceil(contracts), 1)

        # [NEW — Step 9] Hard cap: if the forced minimum exceeds MAX_RISK_OVERRIDE_MULT ×
        # intended risk, skip the trade rather than silently over-risk the account.
        actual_risk   = contracts_ceiled * stop_pips * pip_value_usd
        intended_risk = risk_amount
        if actual_risk > intended_risk * config.MAX_RISK_OVERRIDE_MULT:
            log.warning(
                "PositionSizer: min 1 contract risks $%.2f (%.1f%% of account) "
                "— exceeds %.1fx intended ($%.2f) — returning 0 to skip trade",
                actual_risk, actual_risk / balance * 100,
                config.MAX_RISK_OVERRIDE_MULT, intended_risk,
            )
            return 0.0
        return contracts_ceiled


class EquityGuard:
    """
    Track running balance and drawdown.
    - Below soft_dd  → scale risk down linearly to 25 %
    - At hard_dd     → halt trading, require manual reset
    """

    def __init__(
        self,
        db_path:         str,
        initial_balance: float = config.INITIAL_BALANCE,
        soft_dd:         float = config.SOFT_DRAWDOWN,
        hard_dd:         float = config.HARD_DRAWDOWN,
    ) -> None:
        self.db_path         = db_path
        self.start_balance   = initial_balance
        self.current_balance = initial_balance
        self.soft_dd         = soft_dd
        self.hard_dd         = hard_dd
        self.halted          = False
        self.risk_scale      = 1.0

    def update(self, new_balance: float) -> None:
        self.current_balance = new_balance
        drawdown = 1.0 - (self.current_balance / self.start_balance)

        if drawdown >= self.hard_dd:
            if not self.halted:
                log.warning("HARD DRAWDOWN %.1f %% reached — trading HALTED", drawdown * 100)
            self.halted     = True
            self.risk_scale = 0.0
        elif drawdown >= self.soft_dd:
            progress        = (drawdown - self.soft_dd) / (self.hard_dd - self.soft_dd)
            self.risk_scale = max(config.RISK_MIN_SCALE, 1.0 - progress * config.RISK_DD_REDUCTION)
            log.info("Soft drawdown %.1f %% — risk scaled to %.0f %%",
                     drawdown * 100, self.risk_scale * 100)
        else:
            self.risk_scale = 1.0

        db.record_equity(self.db_path, new_balance)

    def allow_trade(self) -> bool:
        return not self.halted

    def drawdown_pct(self) -> float:
        return round((1.0 - self.current_balance / self.start_balance) * 100, 2)

    def reset_halt(self) -> None:
        """Call manually after reviewing the account."""
        self.halted     = False
        self.risk_scale = 1.0
        log.info("Equity guard halt reset")


# ── [NEW — Step 5] Daily loss guard ───────────────────────────────────────────

class DailyLossGuard:
    """
    Pause trading for the rest of the calendar day if net P&L on closed trades
    falls below -DAILY_LOSS_LIMIT × balance.

    Separate from EquityGuard (total drawdown from start) — this resets each
    UTC calendar day automatically because it queries today's DB records.

    Works for ALL strategies — checks happen before any signal is acted on.
    """

    def __init__(
        self,
        db_path: str,
        balance: float,
        limit:   float = config.DAILY_LOSS_LIMIT,
    ) -> None:
        self.db_path = db_path
        self.balance = balance
        self.limit   = limit    # fraction of balance, e.g. 0.03 = 3 %

    def update_balance(self, balance: float) -> None:
        """Keep the reference balance current (call after EquityGuard.update)."""
        self.balance = balance

    def allow_trade(self) -> bool:
        """Return False if today's realised losses have hit the daily limit."""
        pnl = db.daily_pnl(self.db_path)
        if pnl < 0 and abs(pnl) >= self.limit * self.balance:
            log.warning(
                "DAILY LOSS LIMIT reached — today's P&L: %.2f  (limit: %.2f %% of %.2f) "
                "— no new trades until tomorrow UTC",
                pnl, self.limit * 100, self.balance,
            )
            return False
        return True

    def daily_loss_pct(self) -> float:
        """Current day's realised loss as a percentage of balance (0 if profitable)."""
        pnl = db.daily_pnl(self.db_path)
        if self.balance <= 0:
            return 0.0
        return round(abs(min(pnl, 0.0)) / self.balance * 100, 2)


# ── [NEW — Step 5] Trailing stop manager ──────────────────────────────────────

class TrailingStopManager:
    """
    Track the best price seen for each open position and compute a tightening
    trailing stop.  Only used for 'trend_following' trades — called from the
    engine loop on every quote poll.

    Stop only ever moves in the profitable direction (ratchets, never worsens).
    Distance from best price = TRAILING_ATR_MULT × current ATR.

    Fix 2 compliance: the *engine* converts the absolute stop level returned here
    into a distance via ig_client.amend_stop — same pattern as order placement.
    Fix 3 compliance: sizing is unaffected (trailing stop does not resize).
    """

    def __init__(
        self,
        atr_mult: float = config.TRAILING_ATR_MULT,
        db_path:  str   = "",                        # [NEW — Step 9] pass config.DB_PATH to persist
    ) -> None:
        self.atr_mult = atr_mult
        self._db_path = db_path
        # Load persisted best prices from DB so restarts don't give back gains
        self._best: dict[str, float] = db.load_trailing_best(db_path) if db_path else {}
        if self._best:
            log.info("[trailing] Restored best-price state for: %s", list(self._best.keys()))

    def update(
        self,
        symbol:        str,
        direction:     str,
        current_price: float,
        current_stop:  float,
        atr:           float,
    ) -> Optional[float]:
        """
        Compute a new trailing stop.

        Returns the new stop level (float) if it should be moved, else None.
        The caller is responsible for submitting the amendment to IG.

        Parameters
        ----------
        symbol        : trading pair key, e.g. "EURUSD"
        direction     : "long" or "short"
        current_price : latest mid/bid/ask price
        current_stop  : stop level currently set on the broker position
        atr           : current ATR value (used to set distance)
        """
        if atr <= 0:
            return None

        best = self._best.get(symbol, current_price)

        if direction == "long":
            best      = max(best, current_price)
            new_stop  = round(best - self.atr_mult * atr, 5)
            improved  = new_stop > current_stop
        else:
            best      = min(best, current_price)
            new_stop  = round(best + self.atr_mult * atr, 5)
            improved  = new_stop < current_stop

        self._best[symbol] = best
        if self._db_path:                                    # [NEW — Step 9] persist on every update
            db.save_trailing_best(self._db_path, symbol, best)

        if improved:
            log.info(
                "[trailing] %s %s  best=%.5f  new_stop=%.5f  (was %.5f)",
                symbol, direction.upper(), best, new_stop, current_stop,
            )
            return new_stop
        return None

    def reset(self, symbol: str) -> None:
        """Call when a position closes to clear the tracked best price."""
        self._best.pop(symbol, None)
        if self._db_path:                                    # [NEW — Step 9]
            db.delete_trailing_best(self._db_path, symbol)


# ── [NEW — Step 7A] Correlation guard ─────────────────────────────────────────

# Map (symbol, direction) → net-USD exposure group.
# USD_LONG  = you are buying USD (short EUR/GBP/etc, long USD/CHF).
# USD_SHORT = you are selling USD (long EUR/GBP/etc, short USD/CHF).
# GBPJPY has no USD leg — not in either group (always allowed).
_USD_GROUP: dict[tuple[str, str], str] = {
    ("EURUSD", "long"):  "USD_SHORT",
    ("EURUSD", "short"): "USD_LONG",
    ("GBPUSD", "long"):  "USD_SHORT",
    ("GBPUSD", "short"): "USD_LONG",
    ("USDCHF", "long"):  "USD_LONG",
    ("USDCHF", "short"): "USD_SHORT",
}


class CorrelationGuard:
    """
    [NEW — Step 7A] Prevent stacking trades in the same net-USD direction.

    EURUSD and GBPUSD are ~85 % correlated.  Going long both simultaneously
    creates an unintended double-sized USD short.  This guard caps the number
    of open trades per net-USD group at CORR_USD_MAX (default = 1).

    GBPJPY (no USD leg) is always allowed through.
    Any unknown symbol is allowed through (fail open, not closed).
    """

    def __init__(self, max_per_group: int = config.CORR_USD_MAX) -> None:
        self.max_per_group = max_per_group

    def allow_trade(
        self,
        symbol:      str,
        direction:   str,
        open_trades: list[dict],
    ) -> bool:
        """
        Return False if adding this trade would exceed the per-group limit.

        Parameters
        ----------
        symbol      : e.g. "EURUSD"
        direction   : "long" or "short"
        open_trades : list of open trade dicts from db.all_open_trades()
        """
        proposed_group = _USD_GROUP.get((symbol, direction))
        if proposed_group is None:
            return True   # GBPJPY or unrecognised symbol — no restriction

        count = sum(
            1 for t in open_trades
            if _USD_GROUP.get((t["symbol"], t["direction"])) == proposed_group
        )

        if count >= self.max_per_group:
            log.warning(
                "[corr] %s %s -> group %s already has %d/%d trade(s) — blocked",
                symbol, direction, proposed_group, count, self.max_per_group,
            )
            return False
        return True
