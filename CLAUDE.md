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

### COMPLETED — Foundation & Optimization
- [x] Critical bugs fixed (BUG 1-4, exception handling, MT5 timezone, position limits)
- [x] Backtester: trailing stop sim, next-bar entry, 0.5pip slippage, 2pip spread
- [x] Parameter optimization: PF 0.79 → PF 1.42, +55%/pair (medium grid, 2592 combos)
- [x] Walk-forward validation: 42.9% OOS profitable, avg +0.15%/month
- [x] ADX direction filter: +DI/-DI confirms trend signals
- [x] EURUSD dropped (unprofitable across all 256 combos)
- [x] Session windows: 12-16 UTC confirmed optimal
- [x] Code review: dead code removed, indicators centralized, specific exception handling
- [x] Dashboard: pause/resume, live PnL fix, drawdown colors, dynamic pairs, starting balance fix
- [x] MT5 micro lot sizing for small accounts
- [x] Per-asset strategy parameters (commodities vs forex)
- [x] AI Sentiment: Finnhub headlines + Claude Haiku scoring live
- [x] Market headlines displayed on dashboard

### COMPLETED — Deployment
- [x] Contabo Windows VPS (EU, 4vCPU, 8GB, €11.10/mo) — DEPLOYED 2026-03-31
- [x] 4 auto-start tasks: MT5 (/autotrading), Engine (1min), Dashboard (2min), Research (Sundays)
- [x] MT5 terminal.ini: AutoTrading persists across reboots
- [x] Dashboard: http://167.86.95.212:8080
- [x] Weekly research agent: Sundays 18:00 UTC via Task Scheduler
- [x] Deploy workflow: git push locally → git pull on VPS

### Phase 4 — Remaining Polish
- [ ] Telegram daily performance report at 16:00 UTC session close
- [ ] Add filter summary per pair ("USDCHF: Blocked — High Vol + News")
- [ ] Add soft/hard drawdown limit lines to equity curve chart
- [ ] Add trade entry/exit markers on equity curve
- [ ] Add Sharpe ratio to backtest stats
- [ ] WebSocket for real-time updates (replace 5s polling)
- [ ] Create `.env.example` template
- [ ] Remove orphaned test files: test_regime.py, test_switcher.py, test_trend.py
- [ ] News filter: fix DST transition calculation

### Phase 5 — Live Account Migration
- [ ] Demo trade 200+ trades to validate live vs backtest
- [ ] Walk-forward results acceptable on live data
- [ ] All tests pass on live config
- [ ] Initial live risk: `RISK_PER_TRADE=0.005` (0.5%) for first 2 weeks
- [ ] Tighter `HARD_DRAWDOWN=0.05` (5%)
- [ ] Separate live DB
- [ ] Telegram alerts confirmed working
- [ ] Manual kill-switch procedure documented
- [ ] Consider UK VPS region for lower latency to Pepperstone

### Phase 6 — Commodity Expansion
- [x] Gold (XAUUSD) and Oil (SPOTCRUDE) added to config with per-asset params
- [x] Gold optimizer: +64%, 35 trades (low confidence — needs more data)
- [x] Oil optimizer: +29.6%, 86 trades, DD 6.2% (solid)
- [ ] Run medium grid optimizer on Gold and Oil for better params
- [ ] Walk-forward validate commodity strategies
- [ ] Explore more Pepperstone commodities: NatGas, Copper, Wheat, Corn
- [ ] Implement cross-asset correlation monitoring
- [ ] Volatility-targeted position sizing across asset classes

### Phase 7 — Stock Trading Exploration
- [ ] Research: which indices/stocks available on Pepperstone MT5 (US500, NAS100, GER40, etc.)
- [ ] Backtest existing MR+TF strategy on index CFDs (US500, NAS100)
- [ ] Research stock-specific strategies: momentum, mean reversion, earnings-based
- [ ] Explore individual stock CFDs if available on Pepperstone
- [ ] Consider Interactive Brokers for broader stock/ETF access
- [ ] Per-asset params for stock indices (different volatility profile)
- [ ] Session window optimization for stock markets (NYSE 14:30-21:00 UTC)
- [ ] Cross-asset portfolio: forex + commodities + indices risk management

### Phase 8 — Unified Trading Engine (Long-term Vision)
- [ ] Full project roadmap in `memory/project_upgrade_roadmap.md`
- [ ] AI Global Macro news layer (Phase 3 of unified plan)
- [ ] Multi-strategy router with adaptive weighting
- [ ] NautilusTrader or PyBroker migration for production-grade execution
- [ ] Portfolio-level risk management across all asset classes

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
