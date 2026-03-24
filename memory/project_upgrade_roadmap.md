# Forex Engine — Project Upgrade Roadmap & Memory

## Overview
Upgraded a single-strategy mean-reversion forex bot into a hybrid multi-strategy bot
that auto-detects market conditions and switches strategies accordingly.

Strict rules applied throughout:
- No deletions of existing logic
- Incremental, confirmed changes per step
- Original mean reversion logic kept intact
- All new code clearly tagged `[NEW — Step N]`

---

## Steps Completed

### Step 1 — Database Schema Extension
Added tables/columns to support multi-strategy storage:
- `signals.strategy` column
- `trades.signal_id` column
- `equity_curve` table

### Step 2 — Market Regime Detection (`strategy/regime_detection.py`)
New standalone module: `detect_market_regime(bars)` → `"ranging"` / `"trending"` / `"high_volatility"`
- ADX (Wilder smoothing) for trend strength
- ATR spike detection for volatility pause
- All parameters centralised in `core/config.py`

### Step 3 — Trend Following Strategy (`strategy/trend_following.py`)
New strategy: `trend_following_signal(bars)` → signal dict or None
- EMA fast/slow crossover entry
- ATR-based stop and target
- Only fires on the crossover bar (not sustained trends)
- All parameters centralised in `core/config.py`

### Step 4 — Strategy Switcher (`engine.py`)
Wired regime detection and trend following into the main engine loop:
- `select_strategy(regime, bars)` routes to correct strategy
- `ranging` → mean reversion (existing)
- `trending` → trend following (new)
- `high_volatility` → skip trade

### Step 5 — Advanced Risk Controls (`risk/guard.py`, `engine.py`)
- `DailyLossGuard`: pause all new trades if today's realised P&L falls below -DAILY_LOSS_LIMIT × balance. Resets automatically each UTC calendar day.
- `TrailingStopManager`: ATR-based ratcheting stop for trend_following trades only. Stop only moves in profitable direction.

### Step 7A — Correlation Control (`risk/guard.py`, `core/db.py`, `engine.py`)
Prevents stacking trades in the same net-USD direction (EURUSD long + GBPUSD long = accidental double USD short).

- `CorrelationGuard` class in `risk/guard.py` — maps `(symbol, direction)` to `USD_LONG` / `USD_SHORT` / standalone group
- `db.all_open_trades()` — new function to fetch all open trades across all symbols
- `config.CORR_USD_MAX = 1` — max trades per USD-direction group
- GBPJPY (no USD leg) is always allowed through
- Check runs after `select_strategy()` returns so the signal direction is known

### Step 7B — Multi-Timeframe Entry Confirmation (`strategy/mtf_filter.py`, `data/fetcher.py`, `engine.py`)
Confirms 1h signals using 5-minute bar structure before entry.

- `strategy/mtf_filter.py` — new module, `confirm_entry(signal_data, bars_5m) -> bool`
- Confirmation: long needs 5m RSI < 60 OR 5m EMA rising; short needs RSI > 40 OR EMA falling
- Pass-through if insufficient bars (never blocks due to missing data)
- `seed_history()` in `data/fetcher.py` — added `resolution` param (default `"HOUR"` — fully backward compatible)
- Engine seeds 5m history on startup for all pairs (when `MTF_ENABLED = True`)
- New config: `MTF_ENABLED`, `MTF_RESOLUTION`, `MTF_BARS`, `MTF_MIN_BARS`, `MTF_RSI_PERIOD`, `MTF_EMA_PERIOD`

### Step 6 — Vectorised Backtester (`backtest.py`)
- O(n) indicator computation
- Baseline (mean reversion only) vs hybrid (regime-switching) comparison
- `run_backtest()`, `compute_stats()`, `print_report()`
- Usage: `python backtest.py --fetch --symbol EURUSD`

---

## Opus Audit Findings — 2026-03-24

Full codebase audit by Claude Opus. All issues logged here for tracking.

### Critical Bugs / Silent Failures

| # | Issue | File | Status |
|---|-------|------|--------|
| B1 | **OHLC bars never refresh after initial seed** — strategies run on stale data all session | `data/fetcher.py`, `engine.py` | ✅ DONE (Step 8) |
| B2 | **IG-closed positions not detected mid-session** — stopped-out pair stays "open" in DB until restart, blocking new signals | `engine.py` | ✅ DONE (Step 8) |
| B3 | **5m bars never refresh** — MTF filter operates on startup data only, stale within hours | `engine.py`, `data/fetcher.py` | ✅ DONE (Step 8) |
| B4 | **PositionSizer silently exceeds risk budget** — forced minimum 1 contract can risk 3–5× intended amount on GBPJPY/USDCHF with wide stops. No warning logged | `risk/guard.py` | ✅ DONE (Step 9) |
| B5 | **TrailingStopManager state lost on restart** — `_best` dict is in-memory only; trailing stop resets to current price after restart, giving back gains | `risk/guard.py` | ✅ DONE (Step 9) |
| B6 | **`amend_stop` price scale** — stop level sent as human-readable (1.1450) but IG may expect raw (11450) for EUR/USD CFD amendments. Needs API verification | `core/ig_client.py` | TO INVESTIGATE |
| B7 | **`upsert_ohlc` return value** — counts rows attempted, not rows inserted; seed logs can overstate what was actually cached | `core/db.py` | LOW |
| B8 | **Equity table grows forever** — ~960 rows/day, no pruning | `core/db.py` | LOW |

### Missing Features (Pre-Live Checklist)

| # | Feature | Priority | Status |
|---|---------|----------|--------|
| M1 | **Weekend/holiday gate** — SessionGate only checks time-of-day, not day-of-week. Engine spins on Saturdays | `risk/guard.py` | ✅ DONE (Step 8) |
| M2 | **File logging** — currently stdout only; logs lost if running in background | `engine.py` | ✅ DONE (Step 9) |
| M3 | **Error alerting** — no notification if hard drawdown halts, auth fails, or engine crashes | `engine.py` | ✅ DONE (Step 9) |
| M4 | **Economic calendar / news filter** — no protection around NFP, CPI, FOMC releases | new module | FUTURE |
| M5 | **No reconnection backoff** — if IG drops, engine logs errors indefinitely with no backoff | `core/ig_client.py` | ✅ DONE (Step 9) |
| M6 | **Database backup** — SQLite is single store of all trade history, no backup mechanism | ops | FUTURE |
| M7 | **Pip value accuracy** — USDCHF ($12.50) and GBPJPY ($6.30) are hardcoded approximations, can be 5–10% off at current rates | `core/config.py` | FUTURE |

### Code Quality Issues

| # | Issue | File | Status |
|---|-------|------|--------|
| Q1 | **`_atr()` duplicated 3×** — identical copy in `mean_reversion.py`, `trend_following.py`, `regime_detection.py` | strategy/ | ✅ DONE (Step 9) |
| Q2 | **`_rsi()` duplicated** — in `mean_reversion.py` and `mtf_filter.py` with slight differences | strategy/ | ✅ DONE (Step 9) |
| Q3 | **`import pandas as _pd` inside hot loop** — `engine.py` line ~194, inside the per-pair iteration | `engine.py` | ✅ DONE (Step 8) |
| Q4 | **`datetime.utcnow()` deprecated** — used in `db.py` 4× (Python 3.12+) | `core/db.py` | ✅ DONE (Step 9) |
| Q5 | **Module-level config caching** — strategy modules copy config at import time; runtime config changes won't propagate | strategy/*.py | LOW |
| Q6 | **Backtester no spread/slippage** — absolute return numbers untrustworthy; missing ~2–4 pips per round-trip | `backtest.py` | FUTURE |
| Q7 | **Backtester pagination** — `get_history()` only fetches 1 page; `--bars 3000` only returns ~1000 bars | `backtest.py` | FUTURE |

### Risk Gap Summary

| Gap | Detail | Planned Fix |
|-----|--------|-------------|
| DailyLossGuard unrealized P&L | Only counts closed trades — open underwater positions not included | Step 9 |
| PositionSizer hard cap missing | Minimum 1 contract can silently exceed risk budget | Step 9 |
| No max simultaneous positions | Correlation guard limits per-group but not total open count | Step 9 |
| Trailing stop state lost on restart | In-memory only — gains can be given back | Step 9 |

---

## Planned Future Upgrades (not yet implemented)

### Step 8 — Critical Fixes (OHLC Refresh + Position Sync + Weekend Gate) ✅ DONE
Addresses the three most critical gaps identified by Opus audit.

- **B1/B3**: `refresh_bars()` added to `data/fetcher.py` — incremental fetch since last stored bar. Called every `OHLC_REFRESH_INTERVAL_SEC` (120s) for both HOUR and MINUTE_5 resolutions. `ig_client.get_history()` now accepts `from_time` param.
- **B2**: Mid-session position sync every `POSITION_SYNC_INTERVAL_SEC` (60s) — polls `get_open_positions()` and closes any DB trades that IG has stopped out.
- **M1**: `SessionGate.is_open()` — added `now.weekday() < 5` (no weekend trading).
- **Q3**: `import pandas as pd` moved to top of `engine.py` (removed inline import from hot loop).
- New config: `OHLC_REFRESH_INTERVAL_SEC = 120`, `POSITION_SYNC_INTERVAL_SEC = 60`
- Tests: 61/61 passing (6 new Step 8 tests added)

### Step 9 — Polish & Hardening ✅ DONE
- **Q1/Q2**: `strategy/indicators.py` — shared `atr()` and `rsi()`. All 4 strategy modules now import from here; local copies removed.
- **B4**: `PositionSizer.lot_size()` — hard cap: returns 0 (skip trade) when min-1-contract would exceed `MAX_RISK_OVERRIDE_MULT × intended_risk`. Logs a WARNING.
- **B5**: `TrailingStopManager` — `db_path` param added; `_best` dict persisted to new `trailing_state` table in SQLite. Restored on restart.
- **M2**: `RotatingFileHandler` added in `engine.py` — writes to `logs/engine.log` (5 MB, 3 rotations).
- **M3**: `_alert()` helper in `engine.py` — appends to `logs/alerts.log` on auth failure and hard drawdown halt.
- **M5**: Exponential backoff in `ig_client._request()` — 3 retries with 2/4/8s waits on `RequestException`.
- **Q4**: All `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` in `db.py` (5 occurrences).
- **B8**: `db.prune_old_records()` — deletes quotes older than `DB_PRUNE_DAYS` (90). Called on engine startup.
- New config: `MAX_RISK_OVERRIDE_MULT`, `DB_PRUNE_DAYS`, `LOG_FILE`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`, `ALERT_FILE`, `IG_RETRY_MAX`, `IG_RETRY_BASE_SEC`
- Tests: 79/79 passing (18 new Step 9 tests)

### ML Regime Detection
Replace ADX rule with a trained Random Forest classifier.
- Features: ADX, RSI slope, ATR ratio, volume trend, Bollinger width, time-of-day
- Needs labelled training data (hindsight regime per bar)
- Dependency: scikit-learn, trained model file
- Retrain periodically as market behaviour shifts

### COT Report Bias (Weekly)
CFTC Commitment of Traders — net positioning of commercials vs speculators.
- Free data from CFTC website (published weekly, 3-day lag)
- Use as a weekly directional bias filter (don't trade against commercial positioning)
- Practical for our 1h timeframe; weekly data is sufficient

### Economic Calendar / News Filter
Pause trading 15 minutes before/after major scheduled releases (NFP, CPI, rate decisions).
- Economic calendar API (free tiers available)
- Not a signal source — purely a trade-pause gate
- News signal quality degrades rapidly post-release; HFTs dominate

### Portfolio-Level Correlation (Dynamic)
Extend Step 7A from rule-based groups to a rolling 30-day correlation matrix.
- If two open trades have correlation > 0.7, reduce second position size by 50%
- Requires storing price correlation calculations across pairs
- Step 7A (rule-based) is already live and covers the main risk

---

## Production Fixes Applied

### Fix 1 — Per-Instrument Price Scale
EUR/USD CFD returns raw ×10000 from IG API (11510 → 1.1510).
Added `price_scale` per instrument in config. Do NOT use API's `scalingFactor` — inconsistent.

### Fix 2 — Stop/Limit as Distances, Not Absolute Levels
Changed `place_order()` to use `stopDistance`/`limitDistance` (pips from fill).
Prevents `ATTACHED_ORDER_LEVEL_ERROR` caused by market moving between quote and fill.

### Fix 3 — Minimum Deal Size
`max(math.ceil(contracts), 1)` — IG rejects fractional sizes below 1 contract.

### Fix 4 — Real Account Balance
`get_account_balance()` fetches live balance from IG `GET /accounts`.
Replaces hardcoded `INITIAL_BALANCE` on startup and refreshes every loop.
Both `EquityGuard` and `DailyLossGuard` stay in sync with actual account.

### Fix 5 — IG Minimum Stop Distance Guard
Added guard in `engine.py` after signal recalculation:
- Reads `min_stop_pips` from live quote
- If stop is closer than IG minimum, widens stop to `min_stop_pips × MIN_STOP_BUFFER`
- Adjusts target to maintain 2:1 R/R
- Logs the widening for visibility

### Fix 6 — All Hardcoded Values → config.py
28+ magic numbers removed from `engine.py`, `risk/guard.py`, `core/ig_client.py`.
Every tunable parameter is now a named constant in `core/config.py`.

---

## Master Test Suite

**File:** `test_all.py`
**Run:** `python test_all.py`
**Coverage:** 79 tests across all steps + pre-existing fixes
**Pass condition:** All 79 tests pass before merging any change.

---

## Parameter Change History

All changes applied on 2026-03-24 based on best-practices comparison vs industry standards.

| Parameter | Original | Changed To | Reason |
|-----------|----------|------------|--------|
| `MR_RSI_OVERSOLD` | 35.0 | **30.0** | Standard oversold threshold. 35 fired too often on shallow dips, reducing signal quality. |
| `MR_RSI_OVERBOUGHT` | 65.0 | **70.0** | Standard overbought threshold. 65 fired on minor retracements; 70 is higher-conviction. |
| `MR_STOP_ATR_MULT` | 0.8 | **1.5** | 0.8×ATR stop was inside the noise band — frequently stopped out before trade developed. 1.5×ATR is the minimum viable stop for 1h forex. |
| `MR_TARGET_ATR_MULT` | 1.6 | **3.0** | Adjusted to maintain 2:1 R/R with new stop. 3.0 / 1.5 = 2:1 exactly. Previous 1.6/0.8 was also 2:1 but at too tight a distance. |
| `TF_FAST_EMA_PERIOD` | 9 | **12** | 12/26 is the canonical MACD pair — backtested extensively across forex. More reliable than 9/21 for 1h bars. |
| `TF_SLOW_EMA_PERIOD` | 21 | **26** | Paired with fast=12. The 9/21 combo is less proven; 12/26 has decades of empirical support. |
| `TF_STOP_ATR_MULT` | 0.8 | **2.0** | Trend trades need more room. 0.8×ATR for a trend trade guarantees noise stop-outs. 2×ATR is the standard for trend-following systems. |
| `TF_TARGET_ATR_MULT` | 1.6 | **4.0** | 4.0 / 2.0 = 2:1 R/R. Trend trades should run further than mean reversion trades; 4×ATR allows the trend to develop. |
| `SOFT_DRAWDOWN` | 0.02 (2%) | **0.04 (4%)** | 2% soft drawdown triggered risk scaling too aggressively — normal intraday variance could hit it. 4% is the standard soft floor. |
| `HARD_DRAWDOWN` | 0.04 (4%) | **0.08 (8%)** | 4% halt was extremely conservative — professional prop desks use 8–10% as the halt threshold. Prevented recovery from normal losing streaks. |
| `TRAILING_ATR_MULT` | 0.8 | **1.2** | 0.8×ATR trailing stop was too tight — prematurely closed winning trend trades. 1.2×ATR gives room while still locking in gains. |
| `REGIME_ATR_SPIKE_MULT` | 1.5 | **2.0** | 1.5× baseline ATR paused trading on routine volatility spikes. 2.0× only triggers on genuine volatility events (news, flash crashes). |
| `HISTORY_BARS` | 500 | **1000** | 500×1h ≈ 21 days of history. ADX and ATR need sufficient warm-up; 1000 bars ≈ 42 days gives much better indicator initialisation. |

### Parameters Left Unchanged (Already Within Best Practice)

| Parameter | Value | Notes |
|-----------|-------|-------|
| `RISK_PER_TRADE` | 1% | Textbook retail forex risk per trade |
| `DAILY_LOSS_LIMIT` | 3% | Industry standard daily circuit breaker |
| `MAX_SPREAD_PIPS` | 2.0 | Conservative; protects against wide spreads |
| `MR_RSI_PERIOD` | 14 | Standard RSI period |
| `MR_ATR_PERIOD` | 14 | Standard ATR period |
| `TF_ATR_PERIOD` | 14 | Standard ATR period |
| `REGIME_ADX_PERIOD` | 14 | Standard Wilder ADX period |
| `REGIME_ADX_THRESHOLD` | 25.0 | Classic ADX trending threshold |
| `REGIME_ATR_PERIOD` | 14 | Standard |
| `REGIME_ATR_SPIKE_WINDOW` | 20 | Reasonable baseline window |
| `MIN_STOP_BUFFER` | 1.1 | 10% above IG minimum — sensible safety margin |
| `RISK_MIN_SCALE` | 0.25 | Scale to 25% risk at soft drawdown — standard |
| `RISK_DD_REDUCTION` | 0.75 | Linear reduction factor — standard |
| `SESSION_START_UTC` | 12:00 | London/NY overlap start (14:00 SAST) |
| `SESSION_END_UTC` | 16:00 | London/NY overlap end (18:00 SAST) |
| `MR_VWAP_WINDOW` | 20 | Standard VWAP window |
| `ENGINE_TRAILING_ATR_PERIOD` | 14 | Standard |
| `IG_REQUEST_TIMEOUT_SEC` | 15 | Reasonable HTTP timeout |
| `QUOTE_INTERVAL_SEC` | 15 | 4 pairs × 4/min = safe within IG rate limits |
| `ENGINE_STAGGER_SEC` | 2 | Avoids IG rate limit burst |

---

## IG-Imposed Constraints (Not Tunable)

These are enforced by IG and cannot be changed:
- **Minimum deal size**: 1 contract (Fix 3 handles this with `math.ceil`)
- **Minimum stop distance**: Per-instrument, read from `dealingRules.minNormalStopOrLimitDistance` (Fix 5 handles this with the stop widening guard)
- **Order type**: MARKET for instant fill; LIMIT/STOP available but not used
- **Stop/limit format on new orders**: Must use `stopDistance`/`limitDistance` in pips (Fix 2)
- **Stop/limit format on amendments**: Must use absolute `stopLevel` (Fix 2 note in `amend_stop`)

---

## Instruments Wired to Demo Account

| Pair | Epic | Price Scale | Pip Size | Pip Value (USD) |
|------|------|-------------|----------|-----------------|
| EUR/USD | CS.D.EURUSD.CFD.IP | 10000 | 0.0001 | $10.00 |
| GBP/USD | CS.D.GBPUSD.CFD.IP | 1 | 0.0001 | $10.00 |
| USD/CHF | CS.D.USDCHF.CFD.IP | 1 | 0.0001 | $12.50 |
| GBP/JPY | CS.D.GBPJPY.CFD.IP | 1 | 0.01 | $6.30 |

All four pairs update in the dashboard. GBP/JPY appears when the dashboard restarts.

---

## File Map

```
forex-engine/
  engine.py                        — main loop, strategy switcher, risk wiring
  core/
    config.py                      — ALL parameters (edit here only)
    db.py                          — SQLite helpers
    ig_client.py                   — IG REST API wrapper
  strategy/
    mean_reversion.py              — original strategy (unchanged logic)
    trend_following.py             — [NEW Step 3] EMA crossover strategy
    regime_detection.py            — [NEW Step 2] ADX+ATR regime classifier
  risk/
    guard.py                       — SessionGate, SpreadFilter, PositionSizer,
                                     EquityGuard, DailyLossGuard, TrailingStopManager
  data/
    fetcher.py                     — fetch_live_quote, seed_history
  execution/
    gateway.py                     — ExecutionGateway, submit()
  backtest.py                      — [NEW Step 6] vectorised backtester
  test_all.py                      — master test suite (43 tests)
  memory/
    project_upgrade_roadmap.md     — this file
```
