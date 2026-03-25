# Forex Engine — Claude Context

## Project Summary

Fully-automated hybrid multi-strategy forex trading engine running on IG Markets demo account.
Combines mean-reversion and trend-following strategies with regime detection, COT bias filtering,
news blackouts, multi-timeframe confirmation, and correlation controls.

**Owner location:** South Africa (SAST = UTC+2)
**Trading session:** 12:00–16:00 UTC (14:00–18:00 SAST)
**Broker:** IG Markets (demo account Z69JGB)
**Full project history:** `memory/project_upgrade_roadmap.md`

---

## Broker/Platform Constraints

- **OANDA is NOT available in South Africa** — do not recommend OANDA for this project.
- Current broker is IG Markets. If migrating, consider:
  - **Interactive Brokers (IBKR)** — lowest fees, 100+ pairs, Python/Java/C++ APIs
  - **Alpaca** — top-rated for algo trading 2026, developer-friendly, paper trading built-in
  - **FXCM** — 4 API protocols, 99.99% fill rate
  - **cTrader (via Pepperstone/IC Markets)** — Protobuf Open API, lowest latency
  - **MT5** — surpassed MT4 in volume (54.2%), multi-threaded, real tick backtesting

---

## Critical Bugs to Fix (from code review)

### BUG 1 — Trailing stop overwrites target with None (CRITICAL)
**File:** `engine.py` — `_maybe_trail()` method
When trailing stop fires `amend_stop()`, it passes `new_target=None`. This sends a None
target level to IG, potentially removing the take-profit on open positions.
**Fix:** Pass the existing target level through when amending stops.

### BUG 2 — EquityGuard uses stale startup balance (CRITICAL)
**File:** `risk/guard.py` — `EquityGuard` class
`EquityGuard` captures balance at init time and never updates it. After a winning streak,
drawdown is calculated from the original balance, not the high-water mark. This means the
guard triggers too late (or never) on drawdowns from new highs.
**Fix:** Update the reference balance to `max(current_balance, self._peak)` each cycle.

### BUG 3 — DailyLossGuard resets at UTC midnight, not session close
**File:** `risk/guard.py` — `DailyLossGuard`
Daily P&L resets at midnight UTC, but session runs 12:00–16:00 UTC. A loss at 15:00 UTC
on Monday and another at 12:30 UTC on Tuesday are counted separately even though they're
effectively consecutive trading hours.
**Fix:** Reset at session close (16:00 UTC) instead of midnight.

### BUG 4 — Race condition in position sync
**File:** `engine.py` — mid-session sync logic
If IG closes a position (stop hit) between the time we read open positions and when we
check our DB, we might try to close an already-closed position, causing an API error.
**Fix:** Wrap sync close in try/except for position-not-found errors.

---

## Medium Priority Issues

| # | Issue | File |
|---|-------|------|
| M1 | `refresh_bars()` silently swallows API errors — could trade on stale data | `data/fetcher.py` |
| M2 | No max-position-per-pair limit — could stack multiple trades on same pair | `engine.py` |
| M3 | COT fetcher has no timeout on HTTP requests — could hang the engine loop | `data/cot_fetcher.py` |
| M4 | News scraper has no timeout on HTTP requests | `data/news_filter.py` |
| M5 | Backtest spread model missing — returns are optimistic by ~2 pips/trade | `backtest.py` |

---

## Development Roadmap

### Phase 1 — Fix Critical Bugs (Do First)
- [ ] Fix trailing stop None target (BUG 1)
- [ ] Fix EquityGuard high-water mark (BUG 2)
- [ ] Fix DailyLossGuard reset timing (BUG 3)
- [ ] Fix position sync race condition (BUG 4)
- [ ] Add HTTP timeouts to COT fetcher and news scraper (M3, M4)

### Phase 2 — Backtester Improvements (Step 17)
- [ ] Add 2-pip spread cost per round-trip
- [ ] Multi-page OHLC fetch for 3000+ bars
- [ ] Sharpe ratio calculation
- [ ] Per-strategy breakdown (MR vs TF contribution)

### Phase 3 — Walk-Forward Validation (Step 15)
- [ ] Rolling window validation (6mo in-sample, 1mo out-of-sample)
- [ ] Detect parameter overfitting before going live
- [ ] Need 2-3 years of OHLC data (alternative data source or multi-day IG fetch)

### Phase 4 — Daily Performance Report (Step 14)
- [ ] Auto-generate daily summary at 16:00 UTC session close
- [ ] Send via Telegram: trades, PnL, win rate, balance, drawdown
- [ ] Optional `/performance` dashboard page

### Phase 5 — Live Account Migration (Step 16)
- [ ] 500+ trades per pair in backtest
- [ ] Walk-forward results acceptable
- [ ] All tests pass on live config
- [ ] Initial live risk: `RISK_PER_TRADE=0.005` (0.5%) for first 2 weeks
- [ ] Tighter `HARD_DRAWDOWN=0.05` (5%)
- [ ] Separate live DB
- [ ] Telegram alerts confirmed working
- [ ] Manual kill-switch procedure documented

---

## Key Research Findings (for future reference)

### Strategy Best Practices
- **Combining strategies outperforms single-strategy** — trend following + mean reversion smooths performance across regimes (already implemented)
- **RSI + Moving Averages** combined significantly bolster strategies (2025 SAGE study)
- **MACD + RSI** backtest: 73% win rate over 235 trades
- **Backtested Sharpe ratios poorly predict live performance** (R-squared < 0.025) — walk-forward validation is essential

### Risk Management Standards
- 1-2% risk per trade (currently 1% — good)
- Daily drawdown circuit breaker: 3-5% (currently 4% soft — good)
- Maximum drawdown target: stay below 20% (currently 8% hard — conservative, which is fine for demo)
- Reduce to 0.25-0.5% risk for correlated pairs (>0.7 correlation)
- Minimum 1:2 risk-reward ratio (currently 2:1 — good)
- Kill switches mandatory (implemented via hard drawdown halt)

### Common Pitfalls to Avoid
- **Overfitting**: Profit Factors above 2.0 and Sharpe above 3 in backtest are red flags
- **73% of automated trading accounts fail within 6 months** — conservative risk is correct
- **44% of published strategies fail to replicate** on new data
- **Configuration errors cost average 35% of capital** before being identified — thorough testing essential

---

## Running the Project

```bash
# Run engine
python engine.py

# Run tests (must pass before any merge)
python test_all.py

# Run backtest
python backtest.py --fetch --bars 3000

# Run dashboard
cd dashboard && uvicorn app:app --port 8000
```

---

## File Map

See `memory/project_upgrade_roadmap.md` for complete file map, parameter history,
production fixes applied, and IG-imposed constraints.
