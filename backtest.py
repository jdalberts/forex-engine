"""
[NEW — Step 6] Backtesting module — mean reversion (baseline) vs hybrid (regime-switching).

Bar-by-bar simulation on historical OHLCV data.  No lookahead bias: indicator
values at bar i are computed from bars 0..i only (vectorised EWM/rolling handles
this correctly because pandas computes each value from prior rows only).

Assumptions / simplifications:
  - Entry at OPEN of bar after signal (next-bar-open — realistic, no lookahead)
  - Exit checked using bar HIGH and LOW; if both stop and target are in the
    same bar, stop is assumed to hit first (conservative)
  - Max holding period: MAX_HOLD_BARS — position force-closed at bar close
  - One position per symbol at a time (matches live engine behaviour)
  - Trailing stop simulated for trend_following trades (1.2× ATR ratchet)
  - Spread (2 pips) + slippage (0.5 pips) deducted per trade

Usage (PowerShell from project root):
    python backtest.py                      # use DB data (must have run engine first)
    python backtest.py --fetch              # fetch fresh bars from IG before running
    python backtest.py --yahoo              # fetch ~2 years of bars from Yahoo Finance (free)
    python backtest.py --symbol EURUSD      # single pair (default: all configured pairs)
    python backtest.py --bars 3000          # bars to fetch per pair (default: 1500 for Yahoo)
    python backtest.py --balance 20000      # override starting balance
"""

from __future__ import annotations

import argparse
import logging
import math
from datetime import datetime
from typing import Optional

import pandas as pd

from core import config, db

log = logging.getLogger("backtest")

# ── Simulation parameters ──────────────────────────────────────────────────────
WARMUP_BARS        = 50     # bars discarded at start to let indicators warm up
MAX_HOLD_BARS      = 30     # force-close a position after this many bars [optim: was 20 → 30]
SPREAD_COST_PIPS   = 2.0    # round-trip spread deducted from every trade (entry + exit)
SLIPPAGE_PIPS      = 0.5    # [NEW] execution slippage per trade (on top of spread)
SESSION_START_HOUR = 12     # UTC hour — match live engine session gate
SESSION_END_HOUR   = 16     # UTC hour — match live engine session gate
TRAILING_ATR_MULT  = 1.5    # trailing stop distance for trend trades [optim: was 1.2 → 1.5]

# Import indicator constants and functions from existing strategy modules
# (same calculations as live trading — no duplication)
from strategy.mean_reversion import (
    RSI_PERIOD, BB_PERIOD, BB_STD_DEV, ATR_PERIOD as MR_ATR_PERIOD,  # [Step 18] VWAP_WINDOW → BB_PERIOD/BB_STD_DEV
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    STOP_ATR_MULT as MR_STOP_MULT, TARGET_ATR_MULT as MR_TARGET_MULT,
    _rsi, _bb, _atr as _mr_atr,                                       # [Step 18] _vwap → _bb
)
from strategy.trend_following import (
    FAST_EMA_PERIOD, SLOW_EMA_PERIOD,
    STOP_ATR_MULT as TF_STOP_MULT, TARGET_ATR_MULT as TF_TARGET_MULT,
    _ema, _atr as _tf_atr,
)
from strategy.regime_detection import (
    ADX_PERIOD, ADX_TREND_THRESHOLD,
    ATR_SPIKE_WINDOW, ATR_SPIKE_MULT,
    _adx, _atr as _rd_atr,
)
from strategy.indicators import adx_full as _adx_full
from strategy.indicators import macd as _macd


# ── Indicator pre-computation ──────────────────────────────────────────────────

def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute ALL strategy indicators once across the full dataset.
    Vectorised — O(n), not O(n^2).
    """
    # Mean reversion indicators  [Step 18: mr_vwap → mr_bb_upper/mid/lower]
    df["mr_rsi"]  = _rsi(df["close"], RSI_PERIOD)
    df["mr_bb_upper"], df["mr_bb_mid"], df["mr_bb_lower"] = _bb(df, BB_PERIOD, BB_STD_DEV)
    df["mr_atr"]  = _mr_atr(df, MR_ATR_PERIOD)

    # Trend following indicators
    df["tf_fast"]  = _ema(df["close"], FAST_EMA_PERIOD)
    df["tf_slow"]  = _ema(df["close"], SLOW_EMA_PERIOD)
    df["tf_atr"]   = _tf_atr(df)

    # Regime detection indicators (with +DI/-DI for trend direction filter)
    df["rd_plus_di"], df["rd_minus_di"], df["rd_adx"] = _adx_full(df, ADX_PERIOD)
    df["rd_atr"]      = _rd_atr(df)
    df["rd_atr_base"] = df["rd_atr"].rolling(ATR_SPIKE_WINDOW).mean()

    # MACD histogram for momentum filter
    _, _, df["macd_hist"] = _macd(df["close"], fast=12, slow=26, signal=9)

    return df


# ── Per-bar signal generation ──────────────────────────────────────────────────

def _mean_rev_signal(row: pd.Series, prev: pd.Series = None) -> Optional[dict]:
    """Generate mean reversion signal from pre-computed row — returns dict or None."""
    rsi      = row["mr_rsi"]
    bb_upper = row["mr_bb_upper"]
    bb_lower = row["mr_bb_lower"]
    close    = float(row["close"])
    atr      = row["mr_atr"]
    if any(pd.isna(v) for v in [rsi, bb_upper, bb_lower, atr]) or atr <= 0:
        return None
    if rsi < RSI_OVERSOLD and close <= bb_lower:
        direction = "long"
    elif rsi > RSI_OVERBOUGHT and close >= bb_upper:
        direction = "short"
    else:
        return None
    entry = close
    if direction == "long":
        stop, target = entry - MR_STOP_MULT * atr, entry + MR_TARGET_MULT * atr
    else:
        stop, target = entry + MR_STOP_MULT * atr, entry - MR_TARGET_MULT * atr
    return {"strategy": "mean_reversion", "direction": direction,
            "entry": round(entry, 5), "stop": round(stop, 5), "target": round(target, 5)}


def _trend_signal(row: pd.Series, prev: pd.Series) -> Optional[dict]:
    """Generate EMA crossover signal from pre-computed rows — returns dict or None.

    ADX direction filter: only long when +DI > -DI (bulls stronger),
    only short when -DI > +DI (bears stronger). Filters out crossovers
    that go against the dominant directional movement.
    """
    fn, sn = row["tf_fast"],  row["tf_slow"]
    fp, sp = prev["tf_fast"], prev["tf_slow"]
    atr     = row["tf_atr"]
    close   = float(row["close"])
    if any(pd.isna(v) for v in [fn, sn, fp, sp, atr]) or atr <= 0:
        return None
    bullish = (fn > sn) and (fp <= sp)
    bearish = (fn < sn) and (fp >= sp)
    if not bullish and not bearish:
        return None
    direction = "long" if bullish else "short"

    # ADX direction filter — confirm trend direction with +DI/-DI
    plus_di  = row.get("rd_plus_di")
    minus_di = row.get("rd_minus_di")
    if plus_di is not None and minus_di is not None and not pd.isna(plus_di) and not pd.isna(minus_di):
        if direction == "long" and plus_di <= minus_di:
            return None  # bullish crossover but bears still dominate — skip
        if direction == "short" and minus_di <= plus_di:
            return None  # bearish crossover but bulls still dominate — skip

    entry = close
    if direction == "long":
        stop, target = entry - TF_STOP_MULT * atr, entry + TF_TARGET_MULT * atr
    else:
        stop, target = entry + TF_STOP_MULT * atr, entry - TF_TARGET_MULT * atr
    return {"strategy": "trend_following", "direction": direction,
            "entry": round(entry, 5), "stop": round(stop, 5), "target": round(target, 5)}


def _regime(row: pd.Series) -> str:
    """Read pre-computed regime from row values."""
    adx  = row["rd_adx"]
    atr  = row["rd_atr"]
    base = row["rd_atr_base"]
    if any(pd.isna(v) for v in [adx, atr, base]):
        return "ranging"
    if base > 0 and atr > ATR_SPIKE_MULT * base:
        return "high_volatility"
    return "trending" if adx >= ADX_TREND_THRESHOLD else "ranging"


# ── Trade helpers ──────────────────────────────────────────────────────────────

def _check_exit(row: pd.Series, pos: dict):
    """Returns (exited, exit_price, result)."""
    high, low = float(row["high"]), float(row["low"])
    if pos["direction"] == "long":
        if low <= pos["stop"]:
            return True, pos["stop"], "stop"
        if high >= pos["target"]:
            return True, pos["target"], "win"
    else:
        if high >= pos["stop"]:
            return True, pos["stop"], "stop"
        if low <= pos["target"]:
            return True, pos["target"], "win"
    return False, None, None


def _breakeven_stop(pos: dict, row: pd.Series) -> dict:
    """Move stop to entry once price reaches 1:1 R (stop distance of profit)."""
    if pos.get("breakeven_set"):
        return pos
    entry = pos["entry"]
    stop_dist = abs(entry - pos.get("original_stop", pos["stop"]))
    price = float(row["close"])
    if pos["direction"] == "long":
        if price >= entry + stop_dist:  # 1:1 R reached
            if entry > pos["stop"]:
                pos["stop"] = entry
                pos["breakeven_set"] = True
    else:
        if price <= entry - stop_dist:  # 1:1 R reached
            if entry < pos["stop"]:
                pos["stop"] = entry
                pos["breakeven_set"] = True
    return pos


def _trail_stop(pos: dict, row: pd.Series) -> dict:
    """Update trailing stop for trend_following trades. Mutates and returns pos."""
    if pos["strategy"] != "trend_following":
        return pos
    atr = row.get("tf_atr")
    if pd.isna(atr) or atr <= 0:
        return pos
    price = float(row["close"])
    best = pos.get("best_price", pos["entry"])
    if pos["direction"] == "long":
        best = max(best, price)
        new_stop = round(best - TRAILING_ATR_MULT * atr, 5)
        if new_stop > pos["stop"]:
            pos["stop"] = new_stop
    else:
        best = min(best, price)
        new_stop = round(best + TRAILING_ATR_MULT * atr, 5)
        if new_stop < pos["stop"]:
            pos["stop"] = new_stop
    pos["best_price"] = best
    return pos


def _size(signal: dict, balance: float, pair_cfg: dict,
          risk_fraction: float = config.RISK_PER_TRADE) -> int:
    """Position size in contracts — identical logic to PositionSizer (Fix 3)."""
    risk_amount   = balance * risk_fraction
    stop_distance = abs(signal["entry"] - signal["stop"])
    if stop_distance <= 0:
        return 1
    stop_pips  = stop_distance / pair_cfg["pip_size"]
    contracts  = risk_amount / (stop_pips * pair_cfg["pip_value_usd"])
    return max(math.ceil(contracts), 1)   # Fix 3: always round up, min 1


def _pnl(pos: dict, exit_price: float, pair_cfg: dict,
         spread_pips: float = SPREAD_COST_PIPS,
         slippage_pips: float = SLIPPAGE_PIPS) -> float:
    """Realised P&L in USD for a closed position, including spread + slippage."""
    pip_size = pair_cfg["pip_size"]
    pips = ((exit_price - pos["entry"]) / pip_size if pos["direction"] == "long"
            else (pos["entry"] - exit_price) / pip_size)
    pips -= (spread_pips + slippage_pips)   # deduct spread + slippage
    return round(pips * pos["contracts"] * pair_cfg["pip_value_usd"], 2)


# ── Core simulation ────────────────────────────────────────────────────────────

def run_backtest(
    bars:            list[dict],
    pair_cfg:        dict,
    initial_balance: float,
    use_regime:      bool = False,
    session_filter:  bool = False,   # [NEW] only enter signals during 12–16 UTC
) -> dict:
    """
    Simulate trading on `bars`.

    use_regime=False → baseline (mean reversion only)
    use_regime=True  → hybrid (regime-switching)

    Returns a result dict with trades list, equity_curve, and final_balance.
    """
    if len(bars) < WARMUP_BARS + 10:
        return {"trades": [], "equity_curve": [initial_balance],
                "final_balance": initial_balance, "n_bars": 0}

    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    df = _add_indicators(df)

    balance      = initial_balance
    equity_curve = [balance]
    trades       = []
    open_pos     = None
    pending_signal = None   # [NEW] queue signal for next-bar-open entry

    for i in range(WARMUP_BARS, len(df)):
        row  = df.iloc[i]
        prev = df.iloc[i - 1]

        # ── Fill pending signal at this bar's OPEN (next-bar entry) ────────
        if pending_signal is not None and open_pos is None:
            sig   = pending_signal
            entry = float(row["open"])
            atr_val = sig.get("_atr", 0)
            # Recalculate stop/target from actual entry price
            if sig["direction"] == "long":
                stop   = entry - sig["_stop_mult"] * atr_val
                target = entry + sig["_target_mult"] * atr_val
            else:
                stop   = entry + sig["_stop_mult"] * atr_val
                target = entry - sig["_target_mult"] * atr_val
            open_pos = {
                "entry_bar":     i,
                "entry":         round(entry, 5),
                "stop":          round(stop, 5),
                "original_stop": round(stop, 5),
                "target":        round(target, 5),
                "direction":     sig["direction"],
                "strategy":      sig["strategy"],
                "contracts":     _size({"entry": entry, "stop": stop, "target": target,
                                        "direction": sig["direction"]}, balance, pair_cfg),
                "best_price":    entry,
                "breakeven_set": False,
            }
            pending_signal = None

        # ── Check if open position exits on this bar ───────────────────────
        if open_pos:
            # Apply trailing stop before exit check
            if i > open_pos["entry_bar"]:
                open_pos = _trail_stop(open_pos, prev)

            exited, exit_price, result = _check_exit(row, open_pos)
            if not exited and (i - open_pos["entry_bar"]) >= MAX_HOLD_BARS:
                exited, exit_price, result = True, float(row["close"]), "timeout"

            if exited:
                pnl      = _pnl(open_pos, exit_price, pair_cfg)
                balance += pnl
                trades.append({**open_pos, "exit_bar": i,
                               "exit_price": exit_price, "result": result, "pnl": pnl})
                open_pos = None

        # ── Generate signal if flat (queued for next-bar-open entry) ───────
        if open_pos is None and pending_signal is None:
            signal = None

            # Session gate — skip entry outside 12:00–16:00 UTC
            if session_filter:
                bar_hour = row["time"].hour if hasattr(row["time"], "hour") else pd.to_datetime(row["time"]).hour
                if not (SESSION_START_HOUR <= bar_hour < SESSION_END_HOUR):
                    equity_curve.append(balance)
                    continue

            if use_regime:
                reg = _regime(row)
                if reg == "ranging":
                    signal = _mean_rev_signal(row, prev)
                elif reg == "trending":
                    signal = _trend_signal(row, prev)
                # else: high_volatility → no signal
            else:
                signal = _mean_rev_signal(row, prev)   # baseline: always mean reversion

            if signal:
                # Queue for next-bar open — store ATR and multipliers for recalculation
                atr_key = "mr_atr" if signal["strategy"] == "mean_reversion" else "tf_atr"
                stop_mult = MR_STOP_MULT if signal["strategy"] == "mean_reversion" else TF_STOP_MULT
                target_mult = MR_TARGET_MULT if signal["strategy"] == "mean_reversion" else TF_TARGET_MULT
                signal["_atr"] = row[atr_key]
                signal["_stop_mult"] = stop_mult
                signal["_target_mult"] = target_mult
                pending_signal = signal

        equity_curve.append(balance)

    # Force-close any position still open at end of data
    if open_pos:
        exit_price = float(df.iloc[-1]["close"])
        pnl        = _pnl(open_pos, exit_price, pair_cfg)
        balance   += pnl
        trades.append({**open_pos, "exit_bar": len(df) - 1,
                       "exit_price": exit_price, "result": "open_at_end", "pnl": pnl})
        equity_curve.append(balance)

    return {
        "trades":          trades,
        "equity_curve":    equity_curve,
        "final_balance":   round(balance, 2),
        "initial_balance": initial_balance,
        "n_bars":          len(df) - WARMUP_BARS,
        "date_from":       str(df.iloc[WARMUP_BARS]["time"])[:10],
        "date_to":         str(df.iloc[-1]["time"])[:10],
    }


# ── Statistics ────────────────────────────────────────────────────────────────

def compute_stats(result: dict) -> dict:
    """Derive performance metrics from a backtest result dict."""
    trades  = result["trades"]
    equity  = result["equity_curve"]
    initial = result["initial_balance"]
    final   = result["final_balance"]

    if not trades:
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_return_pct": 0, "max_drawdown_pct": 0,
                "profit_factor": 0, "final_balance": round(final, 2)}

    wins   = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "stop"]

    # Max drawdown
    peak   = initial
    max_dd = 0.0
    for bal in equity:
        peak   = max(peak, bal)
        dd     = (peak - bal) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss   = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")

    return {
        "total_trades":    len(trades),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "total_return_pct": round((final - initial) / initial * 100, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "profit_factor":   profit_factor,
        "final_balance":   round(final, 2),
    }


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(symbol: str, bars_count: int, date_from: str, date_to: str,
                 baseline: dict, hybrid: dict) -> None:
    """Print a side-by-side comparison table."""
    b = compute_stats(baseline)
    h = compute_stats(hybrid)

    def fmt(val, suffix=""):
        if val == float("inf"):
            return "  inf"
        return f"{val:>6.1f}{suffix}"

    ret_diff = round(h["total_return_pct"] - b["total_return_pct"], 2)
    dd_diff  = round(h["max_drawdown_pct"] - b["max_drawdown_pct"], 2)
    sign     = "+" if ret_diff >= 0 else ""
    dd_sign  = "+" if dd_diff >= 0 else ""

    print(f"\n{'=' * 62}")
    print(f"  {symbol}  |  {bars_count} bars  |  {date_from} to {date_to}")
    print(f"{'=' * 62}")
    print(f"  {'Metric':<22} {'Mean Reversion':>16} {'Hybrid':>16}")
    print(f"  {'-' * 56}")
    print(f"  {'Trades':<22} {b['total_trades']:>16} {h['total_trades']:>16}")
    print(f"  {'Wins':<22} {b['wins']:>16} {h['wins']:>16}")
    print(f"  {'Win rate':<22} {fmt(b['win_rate'], ' %'):>16} {fmt(h['win_rate'], ' %'):>16}")
    print(f"  {'Total return':<22} {fmt(b['total_return_pct'], ' %'):>16} {fmt(h['total_return_pct'], ' %'):>16}")
    print(f"  {'Max drawdown':<22} {fmt(b['max_drawdown_pct'], ' %'):>16} {fmt(h['max_drawdown_pct'], ' %'):>16}")
    print(f"  {'Profit factor':<22} {fmt(b['profit_factor']):>16} {fmt(h['profit_factor']):>16}")
    print(f"  {'Final balance':<22} ${b['final_balance']:>14,.2f} ${h['final_balance']:>14,.2f}")
    print(f"  {'-' * 56}")
    print(f"  Hybrid vs baseline:  return {sign}{ret_diff} %   drawdown {dd_sign}{dd_diff} %")
    print()


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_from_db(symbol: str, min_bars: int = 200) -> list[dict]:
    """Load cached OHLC bars from SQLite."""
    bars = db.load_ohlc(config.DB_PATH, symbol, "HOUR", limit=5000)
    if len(bars) < min_bars:
        log.warning("[%s] Only %d bars in DB (need >= %d)", symbol, len(bars), min_bars)
    return bars


def _fetch_from_yahoo(symbol: str, max_bars: int = 1500) -> list[dict]:    # [NEW — Step 17]
    """Fetch hourly OHLC bars from Yahoo Finance (free, no API key, ~2 years)."""
    try:
        from data.yahoo_fetcher import fetch_yahoo_bars
        bars = fetch_yahoo_bars(symbol, max_bars=max_bars)
        if bars:
            log.info("[%s] Yahoo Finance: %d bars fetched", symbol, len(bars))
        return bars
    except Exception as exc:
        log.error("Yahoo fetch failed for %s: %s", symbol, exc)
        return []


def _fetch_from_mt5(symbol: str, max_bars: int = 50000) -> list[dict]:
    """Fetch OHLC history from MT5 terminal — up to 50,000 H1 bars (~8 years)."""
    try:
        from core.mt5_client import MT5Client
        import MetaTrader5 as mt5

        client = MT5Client(
            login    = config.MT5_LOGIN,
            password = config.MT5_PASSWORD,
            server   = config.MT5_SERVER,
            path     = config.MT5_PATH,
        )
        if not client.authenticate():
            log.error("MT5 authentication failed — check .env and terminal")
            return []

        mt5_sym = config.PAIRS.get(symbol, {}).get("mt5_symbol", symbol)
        mt5.symbol_select(mt5_sym, True)
        bars = client.get_history(mt5_sym, resolution="HOUR", max_bars=max_bars)
        client.shutdown()

        if bars:
            db.init_db(config.DB_PATH)
            db.upsert_ohlc(config.DB_PATH, symbol, "HOUR", bars)
            log.info("[%s] Fetched and cached %d bars from MT5", symbol, len(bars))
        return bars
    except Exception as exc:
        log.error("MT5 fetch failed: %s", exc)
        return []


def _fetch_from_ig(symbol: str, epic: str, price_scale: int,
                   max_bars: int = 3000) -> list[dict]:
    """Fetch fresh OHLC history from IG and cache it."""
    try:
        from core.ig_client import IGClient
        client = IGClient(
            api_key    = config.IG_API_KEY,
            identifier = config.IG_IDENTIFIER,
            password   = config.IG_PASSWORD,
            account_id = config.IG_ACCOUNT_ID,
            demo       = config.IG_DEMO,
        )
        if not client.authenticate():
            log.error("IG authentication failed — check .env")
            return []
        bars = client.get_history(epic, resolution="HOUR",
                                  max_bars=max_bars, price_scale=price_scale)
        if bars:
            db.init_db(config.DB_PATH)
            db.upsert_ohlc(config.DB_PATH, symbol, "HOUR", bars)
            log.info("[%s] Fetched and cached %d bars from IG", symbol, len(bars))
        return bars
    except Exception as exc:
        log.error("IG fetch failed: %s", exc)
        return []


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Forex backtest — baseline vs hybrid")
    parser.add_argument("--fetch",   action="store_true", help="Fetch fresh bars from IG first")
    parser.add_argument("--mt5",     action="store_true", help="Fetch bars from MT5 terminal (up to 50k H1 bars, ~8 years)")
    parser.add_argument("--yahoo",   action="store_true", help="Fetch ~2yr bars from Yahoo Finance (free, no API key)")
    parser.add_argument("--symbol",  default=None,        help="Single pair, e.g. EURUSD")
    parser.add_argument("--bars",    type=int, default=None, help="Bars to use per pair")
    parser.add_argument("--balance", type=float, default=config.INITIAL_BALANCE,
                        help="Starting balance for simulation")
    args = parser.parse_args()

    # Set sensible default bar counts per source
    if args.bars is None:
        if args.mt5:
            args.bars = 50000   # MT5: ~8 years of H1 data
        elif args.yahoo:
            args.bars = 10000   # Yahoo: ~2 years
        else:
            args.bars = 3000    # IG/DB: limited

    pairs = {args.symbol: config.PAIRS[args.symbol]} if args.symbol else config.PAIRS
    if args.symbol and args.symbol not in config.PAIRS:
        print(f"Unknown symbol '{args.symbol}'. Choices: {list(config.PAIRS)}")
        return

    if args.mt5:
        src = "MT5 terminal"
    elif args.yahoo:
        src = "Yahoo Finance"
    elif args.fetch:
        src = "IG API"
    else:
        src = "DB cache"
    session_filter = args.yahoo or args.mt5   # apply 12–16 UTC gate when using 24h data
    cost_note      = f"{SPREAD_COST_PIPS}pip spread + {SLIPPAGE_PIPS}pip slippage"
    filters_note   = f"session 12–16 UTC + {cost_note}" if session_filter else cost_note
    print(f"\nFOREX BACKTEST  |  balance=${args.balance:,.0f}  |  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"Strategies: Mean Reversion (baseline)  vs  Hybrid (regime-switching)")
    print(f"Data source: {src}  |  Filters: {filters_note}")
    print(f"Note: MTF / COT filters not simulated — live win rate may differ\n")

    all_baseline = []
    all_hybrid   = []

    for symbol, pcfg in pairs.items():
        print(f"Loading {symbol}...", end=" ", flush=True)

        if args.mt5:
            bars = _fetch_from_mt5(symbol, max_bars=args.bars)
        elif args.yahoo:
            bars = _fetch_from_yahoo(symbol, max_bars=args.bars)
        elif args.fetch:
            bars = _fetch_from_ig(symbol, pcfg["epic"], pcfg.get("price_scale", 1), args.bars)
        else:
            bars = _load_from_db(symbol)

        if len(bars) < WARMUP_BARS + 20:
            print(f"SKIP — only {len(bars)} bars (run with --fetch to get more data)")
            continue

        print(f"{len(bars)} bars")

        baseline_result = run_backtest(bars, pcfg, args.balance, use_regime=False, session_filter=session_filter)
        hybrid_result   = run_backtest(bars, pcfg, args.balance, use_regime=True,  session_filter=session_filter)

        print_report(
            symbol     = symbol,
            bars_count = len(bars),
            date_from  = baseline_result["date_from"],
            date_to    = baseline_result["date_to"],
            baseline   = baseline_result,
            hybrid     = hybrid_result,
        )

        all_baseline.extend(baseline_result["trades"])
        all_hybrid.extend(hybrid_result["trades"])

    # ── Overall combined summary ───────────────────────────────────────────
    if len(pairs) > 1 and all_baseline:
        def _combined_stats(trades):
            gross_p = sum(t["pnl"] for t in trades if t["pnl"] > 0)
            gross_l = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
            wins    = sum(1 for t in trades if t["result"] == "win")
            total   = len(trades)
            net_pnl = sum(t["pnl"] for t in trades)
            pf      = round(gross_p / gross_l, 2) if gross_l > 0 else float("inf")
            wr      = round(wins / total * 100, 1) if total > 0 else 0
            ret     = round(net_pnl / (args.balance * len(pairs)) * 100, 2)
            return total, wr, ret, pf

        bt, bwr, bret, bpf = _combined_stats(all_baseline)
        ht, hwr, hret, hpf = _combined_stats(all_hybrid)

        print(f"\n{'=' * 62}")
        print(f"  OVERALL ({len(pairs)} pairs combined)")
        print(f"{'=' * 62}")
        print(f"  {'Metric':<22} {'Mean Reversion':>16} {'Hybrid':>16}")
        print(f"  {'-' * 56}")
        print(f"  {'Total trades':<22} {bt:>16} {ht:>16}")
        print(f"  {'Win rate':<22} {bwr:>15.1f}% {hwr:>15.1f}%")
        print(f"  {'Return (per pair)':<22} {bret:>15.2f}% {hret:>15.2f}%")
        print(f"  {'Profit factor':<22} {bpf:>16} {hpf:>16}")
        sign = "+" if hret >= bret else ""
        print(f"\n  Hybrid vs baseline: {sign}{round(hret - bret, 2)} % return per pair")
        print()


if __name__ == "__main__":
    main()
