"""Risk controls — session gate, spread filter, position sizing, drawdown guard."""

from __future__ import annotations

import logging
import math
from datetime import datetime, time as dtime, timezone

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
        return self.start <= now.time() < self.end

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
        stop_pips = stop_distance / pip_size
        contracts = risk_amount / (stop_pips * pip_value_usd)
        # IG minimum deal size is 1 contract; always round up to avoid
        # MINIMUM_ORDER_SIZE_ERROR (fractional sizes below 1 are rejected)
        return max(math.ceil(contracts), 1)


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
            self.risk_scale = max(0.25, 1.0 - progress * 0.75)
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
