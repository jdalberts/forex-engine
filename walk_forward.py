"""
Walk-forward validation — confirms optimized parameters aren't overfitted.

Splits 8 years of data into rolling windows:
  - In-sample (IS): 6 months — where parameters were "trained"
  - Out-of-sample (OOS): 1 month — unseen data to test on

If OOS results are consistently profitable, parameters are robust.
If OOS collapses while IS looks great, we're overfitting.

Usage:
    python walk_forward.py                  # all pairs, DB data
    python walk_forward.py --symbol USDCHF  # single pair
    python walk_forward.py --mt5            # fetch fresh from MT5
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

import pandas as pd

from core import config, db
from backtest import (
    run_backtest, compute_stats, _add_indicators,
    WARMUP_BARS,
)

logging.basicConfig(level=logging.WARNING)

# Walk-forward window sizes (in H1 bars)
# 1 month ≈ 22 trading days × 24 hours = 528 bars (but with session filter ~4h/day = ~88 bars)
# Using calendar bars (24h) since data includes all hours
IS_MONTHS  = 6    # in-sample window
OOS_MONTHS = 1    # out-of-sample window
BARS_PER_MONTH = 500  # ~21 trading days × 24h ≈ 500 H1 bars


def load_bars(symbol: str, max_bars: int = 60000) -> list[dict]:
    """Load cached bars from DB."""
    return db.load_ohlc(config.DB_PATH, symbol, "HOUR", limit=max_bars)


def walk_forward(bars: list[dict], pair_cfg: dict, balance: float = 20000.0) -> list[dict]:
    """
    Run walk-forward validation on a single pair.

    Returns list of window results, each with IS and OOS stats.
    """
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)

    is_size  = IS_MONTHS * BARS_PER_MONTH
    oos_size = OOS_MONTHS * BARS_PER_MONTH
    step     = oos_size  # slide by OOS size each window

    total_bars = len(df)
    windows = []
    start = 0

    while start + is_size + oos_size <= total_bars:
        is_end  = start + is_size
        oos_end = is_end + oos_size

        is_bars  = df.iloc[start:is_end].to_dict("records")
        oos_bars = df.iloc[is_end:oos_end].to_dict("records")

        # Run backtest on both windows with current parameters
        is_result  = run_backtest(is_bars, pair_cfg, balance, use_regime=True, session_filter=True)
        oos_result = run_backtest(oos_bars, pair_cfg, balance, use_regime=True, session_filter=True)

        is_stats  = compute_stats(is_result)
        oos_stats = compute_stats(oos_result)

        is_from  = str(df.iloc[start]["time"])[:10]
        is_to    = str(df.iloc[is_end - 1]["time"])[:10]
        oos_from = str(df.iloc[is_end]["time"])[:10]
        oos_to   = str(df.iloc[min(oos_end - 1, total_bars - 1)]["time"])[:10]

        windows.append({
            "window":    len(windows) + 1,
            "is_from":   is_from,
            "is_to":     is_to,
            "oos_from":  oos_from,
            "oos_to":    oos_to,
            "is_trades": is_stats["total_trades"],
            "is_wr":     is_stats["win_rate"],
            "is_ret":    is_stats["total_return_pct"],
            "is_pf":     is_stats["profit_factor"],
            "is_dd":     is_stats["max_drawdown_pct"],
            "oos_trades": oos_stats["total_trades"],
            "oos_wr":    oos_stats["win_rate"],
            "oos_ret":   oos_stats["total_return_pct"],
            "oos_pf":    oos_stats["profit_factor"],
            "oos_dd":    oos_stats["max_drawdown_pct"],
        })

        start += step

    return windows


def print_results(symbol: str, windows: list[dict]) -> None:
    """Print walk-forward results table."""
    if not windows:
        print(f"  {symbol}: Not enough data for walk-forward windows")
        return

    print(f"\n{'=' * 100}")
    print(f"  {symbol} — Walk-Forward Validation ({len(windows)} windows)")
    print(f"  IS = {IS_MONTHS}mo in-sample  |  OOS = {OOS_MONTHS}mo out-of-sample")
    print(f"{'=' * 100}")
    print(f"  {'#':>3}  {'IS Period':<23} {'IS Ret%':>8} {'IS PF':>7} {'IS Tr':>6}  |  "
          f"{'OOS Period':<23} {'OOS Ret%':>9} {'OOS PF':>7} {'OOS Tr':>7}")
    print(f"  {'-' * 96}")

    oos_profitable = 0
    oos_total = 0
    oos_returns = []

    for w in windows:
        is_pf_str  = f"{w['is_pf']:.2f}" if w['is_pf'] != float('inf') else "  inf"
        oos_pf_str = f"{w['oos_pf']:.2f}" if w['oos_pf'] != float('inf') else "  inf"

        flag = "+" if w["oos_ret"] > 0 else "-" if w["oos_ret"] < 0 else " "

        print(f"  {w['window']:>3}  {w['is_from']} → {w['is_to']}  "
              f"{w['is_ret']:>+7.1f}% {is_pf_str:>7} {w['is_trades']:>6}  |  "
              f"{w['oos_from']} → {w['oos_to']}  "
              f"{w['oos_ret']:>+8.1f}% {oos_pf_str:>7} {w['oos_trades']:>7}  {flag}")

        if w["oos_trades"] > 0:
            oos_total += 1
            oos_returns.append(w["oos_ret"])
            if w["oos_ret"] > 0:
                oos_profitable += 1

    # Summary
    print(f"  {'-' * 96}")
    if oos_total > 0:
        avg_oos = sum(oos_returns) / len(oos_returns)
        pct_profitable = oos_profitable / oos_total * 100
        print(f"  OOS Summary: {oos_profitable}/{oos_total} windows profitable ({pct_profitable:.0f}%)")
        print(f"  Avg OOS return: {avg_oos:+.2f}%")
        if pct_profitable >= 50:
            print(f"  VERDICT: PASS — parameters appear robust (>{50}% OOS windows profitable)")
        else:
            print(f"  VERDICT: CAUTION — <50% OOS windows profitable, possible overfitting")
    print()

    return {
        "symbol": symbol,
        "windows": oos_total,
        "profitable": oos_profitable,
        "pct_profitable": round(oos_profitable / oos_total * 100, 1) if oos_total > 0 else 0,
        "avg_oos_ret": round(sum(oos_returns) / len(oos_returns), 2) if oos_returns else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Walk-forward validation")
    parser.add_argument("--symbol", default=None, help="Single pair (default: all)")
    parser.add_argument("--mt5", action="store_true", help="Fetch fresh from MT5")
    args = parser.parse_args()

    pairs = {args.symbol: config.PAIRS[args.symbol]} if args.symbol else config.PAIRS

    print(f"\nWALK-FORWARD VALIDATION  |  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"Windows: {IS_MONTHS}mo in-sample + {OOS_MONTHS}mo out-of-sample, sliding by {OOS_MONTHS}mo")
    print(f"Pairs: {', '.join(pairs.keys())}")

    db.init_db(config.DB_PATH)
    all_summaries = []

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
            print(f"  {sym}: {len(bars):,} bars from MT5")
            windows = walk_forward(bars, pcfg)
            summary = print_results(sym, windows)
            if summary:
                all_summaries.append(summary)
        client.shutdown()
    else:
        for sym, pcfg in pairs.items():
            bars = load_bars(sym)
            print(f"  {sym}: {len(bars):,} bars from DB")
            windows = walk_forward(bars, pcfg)
            summary = print_results(sym, windows)
            if summary:
                all_summaries.append(summary)

    # Overall verdict
    if all_summaries:
        total_windows = sum(s["windows"] for s in all_summaries)
        total_profitable = sum(s["profitable"] for s in all_summaries)
        overall_pct = round(total_profitable / total_windows * 100, 1) if total_windows > 0 else 0
        avg_ret = sum(s["avg_oos_ret"] for s in all_summaries) / len(all_summaries)

        print(f"{'=' * 100}")
        print(f"  OVERALL: {total_profitable}/{total_windows} OOS windows profitable ({overall_pct}%)")
        print(f"  Avg OOS return across pairs: {avg_ret:+.2f}%")
        if overall_pct >= 50:
            print(f"  OVERALL VERDICT: PASS")
        else:
            print(f"  OVERALL VERDICT: NEEDS WORK — consider per-pair tuning or strategy enhancements")
        print()


if __name__ == "__main__":
    main()
