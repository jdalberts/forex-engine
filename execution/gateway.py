"""Execution gateway — validates, sizes, submits, and records IG orders."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from core import config, db
from risk.guard import EquityGuard, PositionSizer

log = logging.getLogger(__name__)


class ExecutionGateway:
    """
    Single entry point for turning a signal into a live IG order.

    dry_run=True  → logs everything, touches no broker API (safe default)
    dry_run=False → submits real orders to IG demo/live
    """

    def __init__(
        self,
        client,
        db_path:       str,
        equity_guard:  EquityGuard,
        sizer:         PositionSizer,
        dry_run:       bool = True,
    ) -> None:
        self.client  = client
        self.db_path = db_path
        self.equity  = equity_guard
        self.sizer   = sizer
        self.dry_run = dry_run

        if dry_run:
            log.info("ExecutionGateway running in DRY RUN mode — no orders will be placed")

    def submit(self, signal: dict) -> Optional[int]:
        """
        Run all pre-trade checks, size the trade, submit to IG.
        Returns the trade DB id or None if rejected.
        """
        # 1. Drawdown halt
        if not self.equity.allow_trade():
            log.warning("Trade BLOCKED — hard drawdown halt is active")
            db.update_signal_status(self.db_path, signal["id"], "blocked_drawdown")
            return None

        # 2. Only one open position per symbol
        existing = db.open_trade(self.db_path, signal["symbol"])
        if existing:
            log.info("Trade BLOCKED — position already open for %s", signal["symbol"])
            db.update_signal_status(self.db_path, signal["id"], "blocked_position")
            return None

        # 3. Size the trade (contracts = risk_amount / (stop_pips × pip_value_usd))
        size = self.sizer.lot_size(
            balance       = self.equity.current_balance,
            entry         = signal["entry"],
            stop          = signal["stop"],
            pip_size      = signal.get("pip_size",      0.0001),
            pip_value_usd = signal.get("pip_value_usd", 10.0),
            risk_scale    = self.equity.risk_scale,
        )
        if size <= 0:
            log.error("Calculated size is zero — skipping")
            return None

        direction_ig = "BUY" if signal["direction"] == "long" else "SELL"
        log.info(
            "%s %s %s  size=%.2f  entry=%.5f  stop=%.5f  target=%.5f%s",
            "DRY RUN" if self.dry_run else "SUBMIT",
            direction_ig, signal["symbol"], size,
            signal["entry"], signal["stop"], signal["target"],
            "" if not self.dry_run else "  [no order sent]",
        )

        # 4. Submit to broker
        broker_ref: Optional[str] = None
        if not self.dry_run:
            result = self.client.place_order(
                epic        = signal["epic"],
                direction   = direction_ig,
                size        = size,
                stop_level  = signal["stop"],
                limit_level = signal["target"],
                entry       = signal["entry"],
                pip_size    = signal.get("pip_size", 0.0001),
                currency    = signal["currency"],
            )
            if result is None:
                log.error("IG order submission failed")
                db.update_signal_status(self.db_path, signal["id"], "order_failed")
                return None
            broker_ref = result.get("dealReference")

            # Confirm the deal was actually accepted (not just received)
            if broker_ref:
                confirm = self.client.confirm_order(broker_ref)
                if confirm and confirm.get("dealStatus") != "ACCEPTED":
                    reason = confirm.get("reason", "UNKNOWN")
                    log.error("Deal REJECTED by IG  reason=%s — not recording trade", reason)
                    db.update_signal_status(self.db_path, signal["id"], "order_failed")
                    return None

        # 5. Persist
        db.update_signal_status(self.db_path, signal["id"], "submitted")
        trade_id = db.insert_trade(self.db_path, {
            "signal_id":   signal["id"],
            "broker_ref":  broker_ref or "DRY_RUN",
            "symbol":      signal["symbol"],
            "direction":   signal["direction"],
            "size":        size,
            "entry_price": signal["entry"],
            "stop_level":  signal["stop"],
            "limit_level": signal["target"],
            "opened_at":   datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        })
        log.info("Trade recorded  id=%d  broker_ref=%s", trade_id, broker_ref or "DRY_RUN")
        return trade_id
