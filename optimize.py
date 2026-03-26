"""
Parameter optimization for forex backtest.

Sweeps key strategy parameters and ranks by profit factor + return.
Uses MT5 data cached from previous backtest run (or fetches fresh).

Optimized: precomputes indicators per unique period set, then sweeps
threshold/stop/target combos without recomputing indicators.

Usage:
    python optimize.py              # full grid (~30 min)
    python optimize.py --quick      # fewer combinations, faster
    python optimize.py --mt5        # fetch fresh data from MT5 first
"""

from __future__ import annotations

import argparse
import itertools
import logging
import time
from datetime import datetime

import pandas as pd

from core import config, db
from backtest import (
    run_backtest, compute_stats,
    WARMUP_BARS, SLIPPAGE_PIPS,
)

# We'll monkey-patch strategy constants before each run
import strategy.mean_reversion as mr_mod
import strategy.trend_following as tf_mod
import strategy.regime_detection as rd_mod
import backtest as bt_mod

logging.basicConfig(level=logging.WARNING)


def load_bars(symbol: str, max_bars: int = 10000) -> list[dict]:
    """Load cached bars from DB."""
    return db.load_ohlc(config.DB_PATH, symbol, "HOUR", limit=max_bars)


def run_with_params(bars: list[dict], pair_cfg: dict, params: dict,
                    balance: float = 20000.0) -> dict:
    """Run backtest with overridden parameters. Returns stats dict + params."""

    # Mean reversion params
    mr_mod.RSI_OVERSOLD     = params["mr_rsi_os"]
    mr_mod.RSI_OVERBOUGHT   = params["mr_rsi_ob"]
    mr_mod.BB_STD_DEV       = params["mr_bb_std"]
    mr_mod.STOP_ATR_MULT    = params["mr_stop_mult"]
    mr_mod.TARGET_ATR_MULT  = params["mr_target_mult"]

    # Trend following params
    tf_mod.FAST_EMA_PERIOD  = params["tf_fast_ema"]
    tf_mod.SLOW_EMA_PERIOD  = params["tf_slow_ema"]
    tf_mod.STOP_ATR_MULT    = params["tf_stop_mult"]
    tf_mod.TARGET_ATR_MULT  = params["tf_target_mult"]

    # Regime detection
    rd_mod.ADX_TREND_THRESHOLD = params["adx_threshold"]

    # Backtest module params
    bt_mod.SPREAD_COST_PIPS    = params.get("spread_pips", 2.0)
    bt_mod.SLIPPAGE_PIPS       = 0.5  # fixed — realistic assumption
    bt_mod.SESSION_START_HOUR  = params.get("session_start", 12)
    bt_mod.SESSION_END_HOUR    = params.get("session_end", 16)
    bt_mod.MAX_HOLD_BARS       = params.get("max_hold", 20)
    bt_mod.TRAILING_ATR_MULT   = params.get("trail_atr", 1.2)

    # Also update the backtest module's imported references
    bt_mod.RSI_OVERSOLD    = params["mr_rsi_os"]
    bt_mod.RSI_OVERBOUGHT  = params["mr_rsi_ob"]
    bt_mod.BB_STD_DEV      = params["mr_bb_std"]
    bt_mod.MR_STOP_MULT    = params["mr_stop_mult"]
    bt_mod.MR_TARGET_MULT  = params["mr_target_mult"]
    bt_mod.FAST_EMA_PERIOD = params["tf_fast_ema"]
    bt_mod.SLOW_EMA_PERIOD = params["tf_slow_ema"]
    bt_mod.TF_STOP_MULT    = params["tf_stop_mult"]
    bt_mod.TF_TARGET_MULT  = params["tf_target_mult"]
    bt_mod.ADX_TREND_THRESHOLD = params["adx_threshold"]

    result = run_backtest(bars, pair_cfg, balance, use_regime=True, session_filter=True)
    stats  = compute_stats(result)
    stats["params"] = params
    return stats


# ── Parameter grid ───────────────────────────────────────────────────────────

FULL_GRID = {
    "mr_rsi_os":       [20, 25, 30],
    "mr_rsi_ob":       [70, 75, 80],
    "mr_bb_std":       [2.0, 2.5],
    "mr_stop_mult":    [1.5, 2.0, 2.5],
    "mr_target_mult":  [3.0, 4.0, 5.0],
    "tf_fast_ema":     [12, 20],
    "tf_slow_ema":     [26, 50],
    "tf_stop_mult":    [2.0, 2.5, 3.0],
    "tf_target_mult":  [4.0, 5.0, 6.0],
    "adx_threshold":   [20, 25],
    "session_end":     [16, 17],
    "max_hold":        [20, 30, 40],
    "trail_atr":       [1.2, 1.5, 2.0],
}

QUICK_GRID = {
    "mr_rsi_os":       [20, 25],
    "mr_rsi_ob":       [75, 80],
    "mr_bb_std":       [2.0],
    "mr_stop_mult":    [2.0, 2.5],
    "mr_target_mult":  [4.0, 5.0],
    "tf_fast_ema":     [12, 20],
    "tf_slow_ema":     [50],
    "tf_stop_mult":    [2.5, 3.0],
    "tf_target_mult":  [5.0, 6.0],
    "adx_threshold":   [20, 25],
    "session_end":     [16],
    "max_hold":        [30],
    "trail_atr":       [1.5],
}

# Session window grid — keeps optimized params fixed, only varies session hours
SESSION_GRID = {
    "mr_rsi_os":       [25],
    "mr_rsi_ob":       [75],
    "mr_bb_std":       [2.0],
    "mr_stop_mult":    [2.0],
    "mr_target_mult":  [5.0],
    "tf_fast_ema":     [20],
    "tf_slow_ema":     [50],
    "tf_stop_mult":    [2.5],
    "tf_target_mult":  [6.0],
    "adx_threshold":   [20],
    "session_start":   [7, 8, 10, 12],
    "session_end":     [16, 17, 18, 20],
    "max_hold":        [30],
    "trail_atr":       [1.5],
}

# Fixed params (not swept)
FIXED = {
    "session_start": 12,
    "spread_pips":   2.0,
}


def generate_combos(grid: dict) -> list[dict]:
    """Generate all valid parameter combinations from grid."""
    keys = list(grid.keys())
    values = list(grid.values())
    combos = []
    for vals in itertools.product(*values):
        # FIXED provides defaults; grid values override them
        combo = {**FIXED, **dict(zip(keys, vals))}
        # Skip invalid combos
        if combo["mr_rsi_os"] >= combo["mr_rsi_ob"]:
            continue
        if combo["tf_fast_ema"] >= combo["tf_slow_ema"]:
            continue
        if combo["mr_target_mult"] <= combo["mr_stop_mult"]:
            continue
        if combo["tf_target_mult"] <= combo["tf_stop_mult"]:
            continue
        if combo.get("session_start", 12) >= combo.get("session_end", 16):
            continue
        combos.append(combo)
    return combos


def main():
    parser = argparse.ArgumentParser(description="Parameter optimizer")
    parser.add_argument("--quick", action="store_true", help="Fewer combos, faster")
    parser.add_argument("--session", action="store_true", help="Session window sweep only (keeps other params fixed)")
    parser.add_argument("--mt5",   action="store_true", help="Fetch fresh bars from MT5")
    parser.add_argument("--symbol", default=None, help="Single pair (default: all)")
    parser.add_argument("--bars", type=int, default=10000, help="Max bars per pair (default 10000)")
    parser.add_argument("--top", type=int, default=20, help="Show top N results")
    args = parser.parse_args()

    grid = SESSION_GRID if args.session else (QUICK_GRID if args.quick else FULL_GRID)
    combos = generate_combos(grid)

    pairs = {args.symbol: config.PAIRS[args.symbol]} if args.symbol else config.PAIRS
    symbols = list(pairs.keys())

    print(f"\nPARAMETER OPTIMIZATION  |  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"Grid: {'SESSION' if args.session else 'QUICK' if args.quick else 'FULL'}")
    print(f"Pairs: {', '.join(symbols)}")
    print(f"Parameter combinations: {len(combos)}")
    print(f"Total backtests: {len(combos) * len(symbols)}")
    print()

    # Load all bar data upfront
    db.init_db(config.DB_PATH)
    all_bars = {}

    if args.mt5:
        from core.mt5_client import MT5Client
        import MetaTrader5 as mt5
        client = MT5Client(
            login=config.MT5_LOGIN, password=config.MT5_PASSWORD,
            server=config.MT5_SERVER, path=config.MT5_PATH,
        )
        if not client.authenticate():
            print("MT5 authentication failed!")
            return
        for sym, pcfg in pairs.items():
            mt5_sym = pcfg.get("mt5_symbol", sym)
            mt5.symbol_select(mt5_sym, True)
            bars = client.get_history(mt5_sym, resolution="HOUR", max_bars=50000)
            if bars:
                db.upsert_ohlc(config.DB_PATH, sym, "HOUR", bars)
            all_bars[sym] = bars
            print(f"  {sym}: {len(bars):,} bars from MT5")
        client.shutdown()
    else:
        for sym in symbols:
            bars = load_bars(sym, max_bars=args.bars)
            print(f"  {sym}: {len(bars):,} bars from DB")
            all_bars[sym] = bars

    print(f"\nRunning {len(combos)} combinations...\n")

    results = []
    t0 = time.monotonic()

    for idx, combo in enumerate(combos):
        if (idx + 1) % 100 == 0 or idx == 0:
            elapsed = time.monotonic() - t0
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            remaining = (len(combos) - idx - 1) / rate if rate > 0 else 0
            print(f"  [{idx+1}/{len(combos)}]  {rate:.1f} combos/sec  ~{remaining:.0f}s remaining",
                  flush=True)

        # Run across all pairs, aggregate
        total_trades = 0
        total_wins   = 0
        total_pnl    = 0.0
        gross_profit = 0.0
        gross_loss   = 0.0
        max_dd       = 0.0
        per_pair     = {}

        for sym, pcfg in pairs.items():
            bars = all_bars[sym]
            if len(bars) < WARMUP_BARS + 50:
                continue
            stats = run_with_params(bars, pcfg, combo)
            total_trades += stats["total_trades"]
            total_wins   += stats["wins"]
            per_pair[sym] = stats

            pair_pnl = stats["final_balance"] - 20000.0
            total_pnl += pair_pnl
            if pair_pnl > 0:
                gross_profit += pair_pnl
            else:
                gross_loss += abs(pair_pnl)
            max_dd = max(max_dd, stats["max_drawdown_pct"])

        if total_trades == 0:
            continue

        win_rate = round(total_wins / total_trades * 100, 1)
        pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (
            float("inf") if gross_profit > 0 else 0)
        ret_pct = round(total_pnl / (20000.0 * len(symbols)) * 100, 2)

        results.append({
            "combo":         combo,
            "trades":        total_trades,
            "wins":          total_wins,
            "win_rate":      win_rate,
            "return_pct":    ret_pct,
            "profit_factor": pf,
            "total_pnl":     round(total_pnl, 2),
            "max_dd":        round(max_dd, 2),
            "per_pair":      per_pair,
        })

    elapsed = time.monotonic() - t0
    print(f"\nDone — {len(combos)} combos in {elapsed:.1f}s ({len(combos)/elapsed:.1f}/s)\n")

    # Sort by return %, then profit factor
    results.sort(key=lambda r: (r["return_pct"], r["profit_factor"]), reverse=True)

    # Print top N
    print(f"{'=' * 90}")
    print(f"  TOP {args.top} PARAMETER SETS (by return %)")
    print(f"{'=' * 90}")

    for rank, r in enumerate(results[:args.top], 1):
        c = r["combo"]
        print(f"\n  #{rank}  Return: {r['return_pct']:+.1f}%  |  PF: {r['profit_factor']:.2f}  |  "
              f"WR: {r['win_rate']:.1f}%  |  Trades: {r['trades']}  |  MaxDD: {r['max_dd']:.1f}%")
        print(f"     MR: RSI {c['mr_rsi_os']}/{c['mr_rsi_ob']}  BB {c['mr_bb_std']}σ  "
              f"Stop {c['mr_stop_mult']}×ATR  Target {c['mr_target_mult']}×ATR")
        print(f"     TF: EMA {c['tf_fast_ema']}/{c['tf_slow_ema']}  "
              f"Stop {c['tf_stop_mult']}×ATR  Target {c['tf_target_mult']}×ATR  "
              f"Trail {c.get('trail_atr', 1.2)}×ATR")
        print(f"     Regime: ADX≥{c['adx_threshold']}  Hold≤{c.get('max_hold', 20)}  "
              f"Session 12–{c.get('session_end', 16)} UTC")

        # Per-pair breakdown
        for sym, stats in r["per_pair"].items():
            print(f"       {sym}: {stats['total_trades']} trades  "
                  f"WR={stats['win_rate']:.1f}%  "
                  f"Ret={stats['total_return_pct']:+.1f}%  "
                  f"DD={stats['max_drawdown_pct']:.1f}%")

    # Show worst 5
    print(f"\n{'=' * 90}")
    print(f"  BOTTOM 5 (worst performing)")
    print(f"{'=' * 90}")
    for rank, r in enumerate(results[-5:], 1):
        c = r["combo"]
        print(f"  #{rank}  Return: {r['return_pct']:+.1f}%  |  Trades: {r['trades']}  |  "
              f"MR RSI {c['mr_rsi_os']}/{c['mr_rsi_ob']}  Stop {c['mr_stop_mult']}×  "
              f"Target {c['mr_target_mult']}×  |  TF EMA {c['tf_fast_ema']}/{c['tf_slow_ema']}")

    # Recommended config
    if results and results[0]["return_pct"] > 0:
        best = results[0]["combo"]
        print(f"\n{'=' * 90}")
        print(f"  RECOMMENDED CONFIG.PY UPDATES")
        print(f"{'=' * 90}")
        print(f"  MR_RSI_OVERSOLD      = {best['mr_rsi_os']}")
        print(f"  MR_RSI_OVERBOUGHT    = {best['mr_rsi_ob']}")
        print(f"  MR_BB_STD_DEV        = {best['mr_bb_std']}")
        print(f"  MR_STOP_ATR_MULT     = {best['mr_stop_mult']}")
        print(f"  MR_TARGET_ATR_MULT   = {best['mr_target_mult']}")
        print(f"  TF_FAST_EMA_PERIOD   = {best['tf_fast_ema']}")
        print(f"  TF_SLOW_EMA_PERIOD   = {best['tf_slow_ema']}")
        print(f"  TF_STOP_ATR_MULT     = {best['tf_stop_mult']}")
        print(f"  TF_TARGET_ATR_MULT   = {best['tf_target_mult']}")
        print(f"  TRAILING_ATR_MULT    = {best.get('trail_atr', 1.2)}")
        print(f"  REGIME_ADX_THRESHOLD = {best['adx_threshold']}")
        print()
    else:
        print(f"\n  No profitable parameter set found across all pairs.")
        print(f"  Best result: {results[0]['return_pct']:+.1f}%" if results else "  No results.")
        print(f"  Consider: strategy enhancements (MACD filter, breakeven stop)")
        print()

    # Save top 50 results to CSV for analysis
    if results:
        rows = []
        for r in results[:50]:
            row = {**r["combo"], "return_pct": r["return_pct"], "win_rate": r["win_rate"],
                   "profit_factor": r["profit_factor"], "trades": r["trades"], "max_dd": r["max_dd"]}
            rows.append(row)
        df = pd.DataFrame(rows)
        df.to_csv("optimization_results.csv", index=False)
        print(f"  Top 50 results saved to optimization_results.csv")


if __name__ == "__main__":
    main()
