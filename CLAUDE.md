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

### Phase 4.5 — AI Integration Enhancements [NEW — April 2026 research]

Dispatched 4 research agents (see "AI Trading Research" below). These 5 items came out of that review — ordered by impact/risk:

- [ ] **Fix `test_all.py`** — early `sys.exit(1)` at line 354 blocks Steps 7A-17 from ever running. Also Fix 1b (EURUSD removed from PAIRS), Steps 3a-f (TF EMA changed 12/26 → 20/50), Step 6i (hybrid uses `at least mean_reversion`). Gets CI green so future PRs can rely on the full suite.
- [ ] **Fork `ariadng/metatrader-mcp-server`** — MCP bridge that lets Claude Code read ticks, positions, and equity from the running MT5 terminal in natural language. Low-risk research/monitoring co-pilot. Python engine stays the executor. Fork it, experiment, keep the bot untouched.
- [ ] **Pine Script authoring via Claude** — write XAUUSD + SPOTCRUDE visual-confirmation indicators (MR/TF entry zones, ATR regime shade, COT bias overlay). Store under `pine/` directory. Use for manual chart review on TradingView; does NOT touch live trading loop. Claude Sonnet 4.5/4.6 benchmarked best-in-class for Pine v5/v6 (PickMyTrade).
- [ ] **Re-scope sentiment layer** — current Finnhub + Claude design has weak evidence for forex (headlines are reports of past moves, not predictors). Changes needed:
  - Drop Finnhub as primary source. Use central bank speech feeds (FOMC, ECB, BoJ, BoE) + economic calendar surprise (actual vs consensus).
  - Cache by `(article_hash, prompt_version, model_version)` in SQLite so labels are reproducible across prompt tweaks.
  - Strip tickers/currency names from prompts before classification (kills the "distraction effect" from Claude's general knowledge).
  - Change semantics from continuous **gate** to event-driven **veto / risk-off regime flag**.
  - Cap weight at 10-15% of total signal stack.
  - Walk-forward validate only on data strictly **after** Claude's training cutoff. If you can't commit to this, kill the feature — it will silently inflate every backtest.
- [ ] **Walk-forward validation framework** — Phase 3 originally, now moved up. Every sentiment/prompt/param change from here on needs strict post-cutoff walk-forward or it's compromised. Build a reusable `walk_forward.py` harness over `backtest.py` that slices time into train/test windows and reports out-of-sample stats. Blocks all future parameter tuning.

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

### AI Trading Research (April 2026)

Dispatched 4 parallel research agents covering: real-world LLM trading results, Claude+TradingView integration, open-source AI trading tools, and LLM sentiment for forex. Key findings:

**What actually works (empirical)**
- **LLM-as-sentiment-filter over classical strategy** — Kirtac & Germano (2024): Sharpe 3.05 after 10bps costs on 965k news articles 2010-2023. Best-documented pattern. **But overwhelmingly on US equities, not forex.** (arXiv 2412.19245)
- **LLM as research/code assistant** — where hedge funds actually spend their GenAI budget. No direct alpha claim; they claim faster idea-to-PnL. Resonanz Capital fund survey.
- **LLM-guided RL** for regime detection — hybrid beat RL-only on 4/6 stocks. Maps onto the existing MR/TF regime switcher. (arXiv 2508.02366)
- **Multi-agent "trading desk"** (TradingAgents, HedgeAgents) — academically hot, backtest-only, no audited live PnL. Numbers (70% ann., 400%/3y) trip the project's own overfit heuristics.

**Dominant failure modes**
- **Look-ahead contamination** — Glasserman & Lin (arXiv 2309.17322): GPT sentiment "alpha" in backtests is mostly pretraining memorization. After anonymizing tickers, much of the edge disappears. **Must-read before any sentiment work.**
- **Distraction effect** — larger companies score worse because LLM world-knowledge overrides article text. Fix: strip tickers/names from prompts.
- **Stochastic inference** — same prompt gives different labels across runs. Mitigation: temperature 0, majority voting, cache by `(article_hash, prompt_version)`.
- **News lag** — commercial feeds are 200-2000ms behind price; sentiment alpha decays in seconds on liquid FX. Works only on daily/4H horizons (12-16 UTC window is fine).
- **Prompt overfit** — tuning prompts on the same backtest window is the new curve-fitting.

**LLM as primary signal source**
- **No credible live track record.** Every published win uses the LLM as one input into a classical/RL overlay. Recommendation: keep Claude as a sentiment/veto filter on top of the MR/TF core. **Never let it size or pick direction.**

**Forex-specific sentiment reality**
- **Finnhub is equities-tooled.** FX headlines are reports of past moves ("USD strong on Fed minutes"), not leading indicators.
- **Best FX sources instead**: FOMC/ECB/BoJ/BoE statements and speeches (FXStreet Speech Tracker, KC Fed research on hawkish-dovish scoring), economic calendar surprise, existing COT data.
- `SENTIMENT_REFRESH_SEC=900` is in the dead zone — too slow for news reactions (priced in minutes), too fast for macro drift. Raise to 3600s and treat as daily bias, or drop to ~60s and accept you're still late.
- `SENTIMENT_BLOCK_THRESHOLD=0.5` is raw model confidence, not calibrated P(loss). No production system uses a single threshold this way.

**Claude + TradingView integration**
- **"Code-level price reading"** in practice = Pine Script → MCP → Claude reads OHLCV as structured JSON. Three architectures in the wild:
  1. Pine → MCP → Claude (structured data) — `tradesdontlie/tradingview-mcp` (1.6k ⭐), breaks on TV updates
  2. Chart screenshot → Claude vision — works, slow, expensive
  3. TV webhook → Claude API → broker — hobbyist copy-paste
- **All MCPs are single-author, no tests, no SLAs.** Not production-grade.
- **Claude IS the best LLM for Pine Script v5/v6** (PickMyTrade benchmark vs GPT-5). Use it for indicator authoring.
- **Do NOT add TV+Claude to the live trading loop.** MT5 pipeline is already working; don't add latency and failure modes. Use Claude for Pine authoring only.

**Directly actionable repos**
| Repo | Why |
|---|---|
| `ariadng/metatrader-mcp-server` | MCP bridge for MT5 — plug directly into existing Pepperstone stack as research/monitoring co-pilot |
| `TauricResearch/TradingAgents` (49.4k ⭐) | Cleanest open multi-agent reference. Mine ideas, don't run live. |
| `nautechsystems/nautilus_trader` (9.1k ⭐) | Best-in-class Python+Rust execution engine. Target if MT5 is outgrown. |
| `freqtrade/freqtrade` (40k ⭐) | Production-grade crypto bot. Steal risk/hyperopt/pairlist rotation patterns. |
| `pipiku915/FinMem-LLM-StockTrading` | Layered-memory LLM trader, character profiles. Design inspiration for sentiment. |

**Skip**: Pionex/Kryll/Stoic (grid bots marketed as AI), 3Commas/Cryptohopper "AI" (it's ML param tuning, not LLM reasoning), CrewAI/AutoGen trading tutorials (demos, no live), any sub-500-star `claude-trader`/`llm-tradebot` repo.

**Top 5 sources worth reading**
1. Glasserman & Lin — "Assessing Look-Ahead Bias in GPT Sentiment Trading" (arXiv 2309.17322) — **required reading**
2. Kirtac & Germano — "Sentiment trading with LLMs" (arXiv 2412.19245) — the positive case, rigorous
3. TauricResearch/TradingAgents (GitHub) — multi-agent reference architecture
4. ariadng/metatrader-mcp-server (GitHub) — direct plug-in path
5. Resonanz Capital — "How hedge funds are really using GenAI" — what funds actually deploy

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
