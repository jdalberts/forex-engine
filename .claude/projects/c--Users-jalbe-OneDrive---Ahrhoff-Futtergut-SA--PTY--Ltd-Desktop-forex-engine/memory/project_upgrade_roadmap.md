---
name: Unified Trading Engine Master Roadmap
description: Vision to expand forex-engine into multi-asset platform (forex, commodities, futures) with AI macro analysis. 7 phases, 4-6 months.
type: project
---

## Vision
Expand the profitable forex engine (PF 1.42, 3 pairs) into a unified multi-asset trading platform covering forex, commodities (oil, wheat, gold), and futures — powered by AI global macro analysis.

## Core Principles
- One engine, all asset classes — not separate bots
- Build on existing forex architecture, do not rebuild it
- Backtest everything before deploying live
- AI reads the world — engine responds to what markets dictate

## Existing Architecture to Leverage
These components already work and should be wrapped/extended, NOT rebuilt:
- `backtest.py` — OHLC sim with spread, slippage, trailing stops, next-bar entry
- `optimize.py` — parameter grid search (quick/medium/full/session grids)
- `walk_forward.py` — rolling 6mo IS / 1mo OOS validation
- `strategy/regime_detection.py` — ADX-based regime switching (ranging/trending/high_vol)
- `strategy/indicators.py` — shared RSI, ATR, BB, ADX, MACD indicators
- `engine.py:select_strategy()` — strategy router switching MR/TF by regime
- `risk/guard.py` — equity guard, daily loss, trailing stops, correlation, position sizer
- `core/mt5_client.py` — MT5 broker abstraction
- `dashboard/` — FastAPI live UI with pause/resume, equity curve, trade stats
- Current results: PF 1.42, +55%/pair over 8 years, 3 pairs (GBPUSD, USDCHF, GBPJPY)

## 7 Phases

### Phase 1 — Foundation Audit & Unification (1-2 weeks)
- Audit existing code, document what exists
- Abstract forex-specific logic into generic Asset class
- Create clean folder structure for multi-asset
- Preserve all working forex logic

### Phase 2 — Historical Data Pipeline (2-3 weeks)
- Forex: existing MT5 source retained
- Commodities (Oil, Wheat, Gold): Alpha Vantage or Nasdaq Data Link
- Futures: Interactive Brokers or CME DataMine
- Crisis & event database for scenario testing
- Minimum 10 years history per asset

### Phase 3 — AI Global Macro News Layer (2-3 weeks)
- NewsAPI + ForexFactory + RSS feeds
- Claude API for sentiment analysis (Bullish/Bearish/Neutral per currency/commodity)
- Signal-to-trade mapping (USD Bullish → long USD pairs, etc.)
- Event risk blocking (pause 30min before/after major releases)

### Phase 4 — Hybrid Multi-Strategy Architecture (3-4 weeks)
- Modularize existing MR + TF as pluggable strategy modules
- Add Global Macro strategy (AI news signals)
- Future: Momentum, Carry Trade strategies
- Strategy router with regime-based weighting

### Phase 5 — Backtesting & Optimization (4-6 weeks)
- Cross-reference existing forex backtest results as benchmark
- Walk-forward optimization per asset class
- Crisis scenario testing (2008, COVID, Russia/Ukraine)
- Performance metrics: Sharpe, Sortino, Max DD, Calmar, Win Rate, PF

### Phase 6 — Asset Class Expansion (2-3 weeks per asset)
- Rollout order: Forex (done) → Gold → Oil → Wheat → Full futures
- Futures: handle contract rollover, front-month continuous contracts
- Requires futures-capable broker (Interactive Brokers recommended)

### Phase 7 — Portfolio Risk Management (2-3 weeks)
- Cross-asset correlation limits
- Maximum total exposure caps
- Portfolio-level drawdown circuit breaker
- AI event risk flag → automatic position reduction

## Open Questions (🔴)
1. Which broker for commodities/futures? (Interactive Brokers recommended)
2. Data providers and budget for paid subscriptions?
3. Maximum portfolio drawdown tolerance?
4. Can engine go short on commodities/futures, or long-only?
5. How frequently should AI news be re-analysed?
6. Should strategy router weighting be fixed or adaptive?
7. Minimum acceptable Sharpe Ratio per asset class?
8. Which commodities first? Is IB account already open?

## Research Phase (Before Building)
6 research tracks launched to find the most profitable approach:
1. What strategies actually make money across asset classes (academic + quant fund patterns)
2. AI news trading state of the art (does it work? how fast? which sources?)
3. Existing codebase audit (what to keep, extend, rebuild)
4. Data & broker infrastructure (sources, quality, cost, SA availability)
5. Portfolio risk at scale (correlation, sizing, crisis management)
6. Multi-asset backtesting frameworks (best tools, avoiding overfitting)

## Timeline
Total: 4-6 months, quality-first. Each phase produces testable output before next begins.
