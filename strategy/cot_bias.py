"""[NEW — Step 10] COT bias calculator.

Uses a 52-week net-position index to determine whether large speculators
are at an extreme long or short position — a mean-reversion signal.

Bias output:
    "long"    — specs extremely short (index < threshold) → expect reversal up
    "short"   — specs extremely long  (index > threshold) → expect reversal down
    "neutral" — positioning is not at an extreme → no COT filter applied

Note: USDCHF uses inverted CHF futures (specs net long CHF = bearish USDCHF).
"""

from __future__ import annotations

import logging

from core import config, db

log = logging.getLogger(__name__)

# Pairs whose COT futures are quoted inverse to the FX pair
_INVERTED_SYMBOLS = {"USDCHF"}
# Minimum rows required before we trust the index calculation
_MIN_ROWS = 10


class CotBias:
    def __init__(
        self,
        db_path: str,
        weeks: int = config.COT_WEEKS_HISTORY,
        long_threshold: float = config.COT_LONG_THRESHOLD,
        short_threshold: float = config.COT_SHORT_THRESHOLD,
    ) -> None:
        self._db_path        = db_path
        self._weeks          = weeks
        self._long_threshold = long_threshold
        self._short_threshold = short_threshold

    def get_bias(self, symbol: str) -> str:
        """Return "long", "short", or "neutral" for the given symbol.

        Steps:
        1. Load last `weeks` COT rows from DB for this symbol
        2. If fewer than _MIN_ROWS → return "neutral" (insufficient history)
        3. Compute net_spec 52-week index = (current - min) / (max - min)
        4. Invert index for USDCHF (CHF futures are inverse of USD/CHF)
        5. Apply thresholds → return bias string
        """
        rows = db.load_cot_history(self._db_path, symbol, self._weeks)
        if len(rows) < _MIN_ROWS:
            log.debug("COT %s: only %d rows — returning neutral", symbol, len(rows))
            return "neutral"

        net_specs  = [r["net_spec"] for r in rows]
        current    = net_specs[-1]
        min_val    = min(net_specs)
        max_val    = max(net_specs)

        if max_val == min_val:
            log.debug("COT %s: flat net_spec — returning neutral", symbol)
            return "neutral"

        index = (current - min_val) / (max_val - min_val)

        # Invert for pairs where the futures are quoted inverse to the FX pair
        if symbol in _INVERTED_SYMBOLS:
            index = 1.0 - index

        if index < self._long_threshold:
            bias = "long"
        elif index > self._short_threshold:
            bias = "short"
        else:
            bias = "neutral"

        log.info("COT %s: index=%.3f  bias=%s  (latest_date=%s)",
                 symbol, index, bias, rows[-1]["report_date"])
        return bias

    def summary(self) -> dict[str, str]:
        """Return {symbol: bias} for all tracked pairs — used for startup logging."""
        from data.cot_fetcher import CONTRACT_MAP
        symbols = list(set(CONTRACT_MAP.values()))
        return {sym: self.get_bias(sym) for sym in sorted(symbols)}
