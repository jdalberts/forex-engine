"""MetaTrader 5 client — drop-in replacement for IGClient.

Requires:
  pip install MetaTrader5

The MetaTrader5 package connects to a running MT5 terminal on Windows.
Broker: Pepperstone or IC Markets (or any MT5-compatible broker).

Interface mirrors IGClient exactly so engine.py, gateway.py, and fetcher.py
work without changes.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from core import config

log = logging.getLogger(__name__)

# MT5 timeframe mapping — matches IG resolution strings to MT5 constants.
# Resolved lazily after import to avoid top-level MetaTrader5 import failure
# on systems where the package isn't installed yet.
_TF_MAP: Optional[dict] = None


def _get_tf_map() -> dict:
    global _TF_MAP
    if _TF_MAP is None:
        import MetaTrader5 as mt5
        _TF_MAP = {
            "MINUTE":    mt5.TIMEFRAME_M1,
            "MINUTE_5":  mt5.TIMEFRAME_M5,
            "MINUTE_15": mt5.TIMEFRAME_M15,
            "MINUTE_30": mt5.TIMEFRAME_M30,
            "HOUR":      mt5.TIMEFRAME_H1,
            "HOUR_2":    mt5.TIMEFRAME_H2,
            "HOUR_3":    mt5.TIMEFRAME_H3,
            "HOUR_4":    mt5.TIMEFRAME_H4,
            "DAY":       mt5.TIMEFRAME_D1,
            "WEEK":      mt5.TIMEFRAME_W1,
        }
    return _TF_MAP


class MT5Client:
    """MetaTrader 5 broker client with the same interface as IGClient."""

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        path: str = "",
    ) -> None:
        self.login    = login
        self.password = password
        self.server   = server
        self.path     = path        # path to terminal64.exe (optional)
        self._connected = False

    # ── Authentication ────────────────────────────────────────────────────────

    @property
    def authenticated(self) -> bool:
        return self._connected

    def authenticate(self) -> bool:
        """Initialise MT5 terminal connection and log in."""
        import MetaTrader5 as mt5

        init_kwargs: dict = {
            "login":    self.login,
            "password": self.password,
            "server":   self.server,
            "timeout":  60000,
        }
        if self.path:
            init_kwargs["path"] = self.path

        if not mt5.initialize(**init_kwargs):
            log.error("MT5 initialize() failed: %s", mt5.last_error())
            return False

        info = mt5.account_info()
        log.info("MT5 authenticated — account %d  server=%s  balance=%.2f",
                 info.login, info.server, info.balance)
        self._connected = True
        return True

    def shutdown(self) -> None:
        """Clean shutdown — call when engine stops."""
        import MetaTrader5 as mt5
        mt5.shutdown()
        self._connected = False
        log.info("MT5 connection closed")

    # ── Market data ───────────────────────────────────────────────────────────

    def get_snapshot(self, symbol: str, price_scale: int = 1) -> Optional[dict]:
        """Current bid/ask tick — equivalent to IGClient.get_snapshot().

        price_scale is accepted for interface compatibility but MT5 always
        returns human-readable prices, so it is ignored.
        """
        import MetaTrader5 as mt5

        mt5.symbol_select(symbol, True)  # ensure symbol is in Market Watch
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            log.warning("MT5 tick failed for %s: %s", symbol, mt5.last_error())
            return None

        info = mt5.symbol_info(symbol)
        min_stop_points = info.trade_stops_level if info else 0
        point = info.point if info else 0.0001
        # Convert min stop from points to pips (1 pip = 10 points for 5-digit pairs)
        pip_size = config.PAIRS.get(symbol, {}).get("pip_size", 0.0001)
        min_stop_pips = (min_stop_points * point) / pip_size if pip_size > 0 else 0

        return {
            "bid":    tick.bid,
            "ask":    tick.ask,
            "status": "TRADEABLE",
            "time":   datetime.now(timezone.utc).replace(tzinfo=None),
            "min_stop_pips": min_stop_pips,
        }

    def get_history(
        self,
        symbol: str,
        resolution: str = "HOUR",
        max_bars: int = 500,
        price_scale: int = 1,
        from_time: Optional[datetime] = None,
    ) -> list[dict]:
        """Historical OHLC bars — equivalent to IGClient.get_history().

        price_scale is accepted for interface compatibility but ignored.
        """
        import MetaTrader5 as mt5

        tf_map = _get_tf_map()
        tf = tf_map.get(resolution)
        if tf is None:
            log.error("Unknown resolution %s — valid: %s", resolution, list(tf_map.keys()))
            return []

        if from_time is not None:
            # MT5 copy_rates_range expects naive UTC datetimes.
            # We add a generous buffer (1 day ahead) to ensure we get all recent bars.
            utc_from = from_time.replace(tzinfo=None) if from_time.tzinfo is not None else from_time
            utc_to = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
            rates = mt5.copy_rates_range(symbol, tf, utc_from, utc_to)
        else:
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, max_bars)

        if rates is None or len(rates) == 0:
            log.warning("MT5 returned no bars for %s %s: %s", symbol, resolution, mt5.last_error())
            return []

        bars = []
        for r in rates:
            bars.append({
                "time":   datetime.fromtimestamp(r["time"], tz=timezone.utc).replace(tzinfo=None),
                "open":   float(r["open"]),
                "high":   float(r["high"]),
                "low":    float(r["low"]),
                "close":  float(r["close"]),
                "volume": int(r["tick_volume"]),
            })

        log.info("Fetched %d %s bars for %s", len(bars), resolution, symbol)
        return bars

    # ── Order management ──────────────────────────────────────────────────────

    def place_order(
        self,
        epic: str,
        direction: str,
        size: float,
        stop_level: float,
        limit_level: float,
        entry: float,
        pip_size: float,
        currency: str = "USD",
    ) -> Optional[dict]:
        """Place a market order with stop and take-profit.

        Parameters match IGClient.place_order() exactly.
        `epic` is the MT5 symbol name (e.g. "EURUSD").
        """
        import MetaTrader5 as mt5

        order_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL

        # Get current price for market order
        tick = mt5.symbol_info_tick(epic)
        if tick is None:
            log.error("Cannot get tick for %s: %s", epic, mt5.last_error())
            return None

        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

        # Determine filling mode supported by this symbol.
        # SYMBOL_FILLING_FOK=1, SYMBOL_FILLING_IOC=2 are bitmask values in filling_mode.
        # ORDER_FILLING_FOK=0, ORDER_FILLING_IOC=1, ORDER_FILLING_RETURN=2 are order enum values.
        info = mt5.symbol_info(epic)
        if info is not None:
            if info.filling_mode & 1:   # SYMBOL_FILLING_FOK
                filling = mt5.ORDER_FILLING_FOK
            elif info.filling_mode & 2: # SYMBOL_FILLING_IOC
                filling = mt5.ORDER_FILLING_IOC
            else:
                filling = mt5.ORDER_FILLING_RETURN
            log.debug("Symbol %s filling_mode=%d → using %d", epic, info.filling_mode, filling)
        else:
            filling = mt5.ORDER_FILLING_FOK

        request = {
            "action":      mt5.TRADE_ACTION_DEAL,
            "symbol":      epic,
            "volume":      size,
            "type":        order_type,
            "price":       price,
            "sl":          stop_level,
            "tp":          limit_level,
            "deviation":   20,  # max slippage in points
            "magic":       234000,  # EA magic number to identify our trades
            "comment":     "forex-engine",
            "type_time":   mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        result = mt5.order_send(request)
        if result is None:
            log.error("MT5 order_send returned None: %s", mt5.last_error())
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            log.error("MT5 order failed  retcode=%d  comment=%s", result.retcode, result.comment)
            return None

        log.info("MT5 order placed — ticket=%d  deal=%d", result.order, result.deal)
        return {"dealReference": str(result.order)}

    def confirm_order(self, deal_reference: str) -> Optional[dict]:
        """Check deal status — MT5 orders are synchronous, so this always returns ACCEPTED.

        Included for interface compatibility with IGClient.
        """
        import MetaTrader5 as mt5

        ticket = int(deal_reference)
        # Give MT5 a moment to process
        time.sleep(0.5)

        # Check the order exists
        order = mt5.history_orders_get(ticket=ticket)
        if order and len(order) > 0:
            return {
                "dealStatus": "ACCEPTED",
                "reason": "",
                "level": order[0].price_current,
            }

        # Also check deals (filled trades)
        deals = mt5.history_deals_get(position=ticket)
        if deals and len(deals) > 0:
            return {
                "dealStatus": "ACCEPTED",
                "reason": "",
                "level": deals[0].price,
            }

        return {
            "dealStatus": "ACCEPTED",
            "reason": "",
            "level": 0,
        }

    # ── Account & position management ─────────────────────────────────────────

    def get_account_balance(self) -> Optional[float]:
        """Current account balance."""
        import MetaTrader5 as mt5

        info = mt5.account_info()
        if info is None:
            log.warning("MT5 account_info() failed: %s", mt5.last_error())
            return None
        return float(info.balance)

    def get_open_positions(self) -> list[dict]:
        """All open positions — returns IG-compatible format for engine.py.

        Engine expects: [{"market": {"epic": "EURUSD"}, "position": {"dealId": "12345"}}, ...]
        """
        import MetaTrader5 as mt5

        positions = mt5.positions_get()
        if positions is None:
            return []

        result = []
        for pos in positions:
            result.append({
                "market": {
                    "epic": pos.symbol,
                },
                "position": {
                    "dealId": str(pos.ticket),
                },
            })
        return result

    def amend_stop(self, epic: str, new_stop: float, price_scale: int = 1) -> bool:
        """Move the stop-loss on an open position.

        price_scale is accepted for interface compatibility but ignored —
        MT5 always uses human-readable prices.
        """
        import MetaTrader5 as mt5

        positions = mt5.positions_get(symbol=epic)
        if not positions:
            log.warning("amend_stop: no open position for %s", epic)
            return False

        pos = positions[0]  # take first position for this symbol

        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   epic,
            "position": pos.ticket,
            "sl":       new_stop,
            "tp":       pos.tp,     # preserve existing take-profit
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            log.error("MT5 amend_stop failed for %s: %s",
                      epic, result.comment if result else mt5.last_error())
            return False

        log.info("Stop amended  symbol=%s  ticket=%d  new_stop=%.5f",
                 epic, pos.ticket, new_stop)
        return True

    def close_position(self, deal_id: str, direction: str, size: float) -> Optional[dict]:
        """Close a position by ticket (deal_id).

        direction: opposite of opening direction (e.g. "SELL" to close a long).
        """
        import MetaTrader5 as mt5

        ticket = int(deal_id)
        order_type = mt5.ORDER_TYPE_SELL if direction.upper() == "SELL" else mt5.ORDER_TYPE_BUY

        # Get current tick for close price
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            log.warning("close_position: ticket %s not found", deal_id)
            return None

        pos = positions[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            log.error("Cannot get tick for %s", pos.symbol)
            return None

        price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask

        # Determine filling mode (same logic as place_order)
        info = mt5.symbol_info(pos.symbol)
        filling = mt5.ORDER_FILLING_FOK
        if info is not None:
            if info.filling_mode & 1:
                filling = mt5.ORDER_FILLING_FOK
            elif info.filling_mode & 2:
                filling = mt5.ORDER_FILLING_IOC

        request = {
            "action":      mt5.TRADE_ACTION_DEAL,
            "symbol":      pos.symbol,
            "volume":      size,
            "type":        order_type,
            "position":    ticket,
            "price":       price,
            "deviation":   20,
            "magic":       234000,
            "comment":     "forex-engine close",
            "type_filling": filling,
            "type_time": mt5.ORDER_TIME_GTC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            log.error("MT5 close failed  ticket=%s: %s",
                      deal_id, result.comment if result else mt5.last_error())
            return None

        log.info("Position closed  ticket=%s  deal=%d", deal_id, result.deal)
        return {"dealStatus": "CLOSED", "deal": result.deal}
