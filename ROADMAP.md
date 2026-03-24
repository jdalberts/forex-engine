# Forex Engine — Project Roadmap

> Automated CFD trading system for forex pairs via IG Markets.
> Current state: **v1 — single-strategy, demo-tested, production-ready architecture.**

---

## Phase 1: Foundation Hardening (Current → Near-Term)

### Testing & Reliability
- [ ] Unit tests for all core modules (`strategy/`, `risk/`, `execution/`, `core/`)
- [ ] Integration tests for the IG client (mocked API responses)
- [ ] End-to-end dry-run regression test (full engine cycle)
- [ ] CI pipeline (GitHub Actions) — lint, test, type-check on every push

### Documentation
- [ ] README with setup instructions, architecture diagram, and quick-start guide
- [ ] `.env.example` template for required credentials
- [ ] Contribution guidelines

### Logging & Observability
- [ ] Structured logging (JSON format) for machine-parseable logs
- [ ] Trade audit trail — immutable record of every decision and its rationale
- [ ] Dashboard alert banner for hard-drawdown halt or IG auth failures

---

## Phase 2: Strategy & Risk Enhancements

### Strategy Improvements
- [ ] Multi-timeframe confirmation (e.g. 4h trend + 1h mean-reversion entry)
- [ ] Configurable RSI/VWAP thresholds per pair (currently hardcoded)
- [ ] Cooldown period tuning per pair volatility profile
- [ ] Bollinger Band squeeze filter for range-bound confirmation
- [ ] Strategy backtesting framework — replay historical OHLC through signal engine

### Risk Management
- [ ] Trailing stop-loss (ATR-based or fixed pip trail)
- [ ] Time-based stop — auto-close positions held beyond N hours
- [ ] Correlation guard — limit exposure across correlated pairs (e.g. EUR/USD + GBP/USD)
- [ ] Daily loss limit (separate from drawdown guard)
- [ ] Risk profile presets (conservative / moderate / aggressive) selectable at startup

### Order Execution
- [ ] Limit orders (enter at better price instead of market)
- [ ] Partial close / scale-out at intermediate targets
- [ ] Slippage tracking and reporting

---

## Phase 3: Data & Market Intelligence

### Market Data
- [ ] WebSocket streaming (replace 15s polling) for lower latency
- [ ] Multi-resolution OHLC storage (1m, 5m, 15m, 1h, 4h)
- [ ] Tick-level data capture for post-session analysis

### Filters & Context
- [ ] Economic calendar integration — avoid trading around high-impact news (NFP, FOMC, etc.)
- [ ] Session volatility filter — skip unusually quiet or volatile sessions
- [ ] Spread spike detection — pause trading during liquidity drops

---

## Phase 4: Dashboard & UX

### Dashboard Enhancements
- [ ] WebSocket push updates (replace 5s polling)
- [ ] Per-pair P&L chart (not just aggregate equity curve)
- [ ] Trade annotation — click a trade to see entry rationale, indicators at time of signal
- [ ] Daily/weekly/monthly performance summaries
- [ ] Configurable dashboard layout (drag-and-drop cards)

### Controls & Configuration
- [ ] Start/stop engine from dashboard (currently CLI-only)
- [ ] Toggle dry-run ↔ live mode from UI
- [ ] Risk parameter sliders (risk %, drawdown thresholds)
- [ ] Pair enable/disable toggles
- [ ] Manual trade entry / emergency close-all button

---

## Phase 5: Multi-Strategy & Scalability

### Additional Strategies
- [ ] Breakout strategy (range breakout during London open)
- [ ] Momentum strategy (trend-following with moving average crossovers)
- [ ] Strategy selector — run multiple strategies concurrently with independent risk budgets
- [ ] Strategy performance comparison dashboard

### Pair Expansion
- [ ] Add AUD/USD, NZD/USD, USD/CAD, EUR/GBP
- [ ] Per-pair configuration profiles (session windows, pip values, spread limits)
- [ ] Cross-pair signal correlation analysis

### Infrastructure
- [ ] Migrate from SQLite to PostgreSQL for concurrent access at scale
- [ ] Containerized deployment (Docker + docker-compose)
- [ ] Cloud deployment guide (VPS / AWS / Azure)
- [ ] Process supervisor (systemd / PM2) for auto-restart on crash
- [ ] Secure `.env` management (vault or encrypted secrets)

---

## Phase 6: Analytics & Reporting

- [ ] Sharpe ratio, max drawdown, win rate, expectancy calculations
- [ ] Monthly performance reports (auto-generated)
- [ ] Trade journal export (CSV / PDF)
- [ ] Drawdown analysis — visualize drawdown periods on equity curve
- [ ] Strategy attribution — which strategy contributed what to overall P&L

---

## Completed (v1)

- [x] Mean reversion strategy (RSI + VWAP + ATR)
- [x] 4 currency pairs (EUR/USD, GBP/USD, USD/CHF, GBP/JPY)
- [x] Session gating (London/NY overlap, 14:00–18:00 SAST)
- [x] Spread filtering (max 2 pips)
- [x] Dynamic position sizing (risk-based)
- [x] Equity guard (soft 2% / hard 4% drawdown)
- [x] Dry-run mode (default) + live trading (`--live`)
- [x] Deal confirmation (catches silent IG rejections)
- [x] Dynamic price scaling (reads `scalingFactor` from API)
- [x] Real-time dashboard with equity curve
- [x] Trade & signal history logging
- [x] Graceful shutdown (SIGINT/SIGTERM)
- [x] Startup position sync (detects externally closed positions)
