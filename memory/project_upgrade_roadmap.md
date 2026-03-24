# Forex Engine — Project Upgrade Roadmap & Memory

## Overview
Upgraded a single-strategy mean-reversion forex bot into a fully-automated hybrid
multi-strategy trading engine with regime detection, news filtering, COT bias, a live
dashboard, and a backtesting page.

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
- EMA fast/slow crossover entry (12/26 MACD-style)
- ATR-based stop (2×ATR) and target (4×ATR) for 2:1 R/R
- Only fires on the crossover bar (not sustained trends)

### Step 4 — Strategy Switcher (`engine.py`)
Wired regime detection and trend following into the main engine loop:
- `ranging` → mean reversion
- `trending` → trend following
- `high_volatility` → skip trade

### Step 5 — Advanced Risk Controls (`risk/guard.py`, `engine.py`)
- `DailyLossGuard`: pause all new trades if today's realised P&L falls below -3% of balance
- `TrailingStopManager`: ATR-based ratcheting stop for trend_following trades only

### Step 6 — Vectorised Backtester (`backtest.py`)
- O(n) indicator computation, no lookahead bias
- Baseline (mean reversion only) vs hybrid (regime-switching) comparison
- `run_backtest()`, `compute_stats()`, `print_report()`
- Usage: `python backtest.py --fetch --bars 3000`

### Step 7A — Correlation Control
Prevents stacking trades in the same net-USD direction.
- `CorrelationGuard` maps `(symbol, direction)` to USD_LONG / USD_SHORT / standalone
- `config.CORR_USD_MAX = 1` — max trades per USD-direction group
- GBPJPY (no USD leg) always allowed through

### Step 7B — Multi-Timeframe Entry Confirmation
Confirms 1h signals using 5-minute bar structure before entry.
- `strategy/mtf_filter.py` — `confirm_entry(signal_data, bars_5m) -> bool`
- Long: 5m RSI < 60 OR 5m EMA rising; short: RSI > 40 OR EMA falling
- Pass-through if insufficient bars (never blocks on missing data)

### Step 8 — Critical Fixes (OHLC Refresh + Position Sync + Weekend Gate) ✅ DONE
- `refresh_bars()` — incremental OHLC top-up every 120s for HOUR and MINUTE_5
- Mid-session position sync every 60s — closes DB trades IG has already stopped out
- `SessionGate.is_open()` — added weekday check (no weekend trading)
- `import pandas` moved to top of `engine.py` (removed from hot loop)

### Step 9 — Polish & Hardening ✅ DONE
- `strategy/indicators.py` — shared `atr()` and `rsi()`, all duplicates removed
- `PositionSizer` hard cap — skips trade if min-1-contract exceeds `MAX_RISK_OVERRIDE_MULT × intended_risk`
- `TrailingStopManager` persists `_best` to `trailing_state` SQLite table (survives restarts)
- `RotatingFileHandler` — `logs/engine.log` (5MB, 3 rotations)
- `_alert()` helper — appends to `logs/alerts.log` on auth failure / hard drawdown halt
- Exponential backoff in `ig_client._request()` — 3 retries, 2/4/8s waits
- `db.prune_old_records()` — deletes quotes older than 90 days on startup
- All `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` in `db.py`

### Step 10 — COT Report Bias Filter ✅ DONE
**Files:** `data/cot_fetcher.py` (new), `strategy/cot_bias.py` (new), `core/db.py`, `engine.py`

CFTC Legacy Futures-Only COT data as a directional macro filter.
- Downloads `https://www.cftc.gov/files/dea/history/deacot{year}.zip` (free, no API key)
- Parses EUR, GBP (Sterling), CHF, JPY currency futures from both old and new CFTC column formats
- 52-week net-spec index: `(current - min_52wk) / (max_52wk - min_52wk)`
  - index < 0.2 → bias LONG (specs extremely short, mean-reversion signal)
  - index > 0.8 → bias SHORT (specs extremely long)
  - 0.2–0.8 → neutral, no filter applied
- USDCHF inverted (CHF futures are CHF/USD, opposite direction)
- `seed_cot()` on startup downloads current + prior year; `refresh_cot()` runs hourly
- `CotBias.get_bias(symbol)` returns "long" / "short" / "neutral"
- Gate in engine: block signal if COT bias contradicts signal direction
- **DB table:** `cot_data (report_date, symbol, net_spec, net_comm)`
- **Config:** `COT_ENABLED`, `COT_LONG_THRESHOLD=0.2`, `COT_SHORT_THRESHOLD=0.8`, `COT_WEEKS_HISTORY=52`, `COT_REFRESH_INTERVAL_SEC=3600`
- **Tests:** 20 new tests; total 99/99 passing

**COT bugs fixed post-deployment:**
- CFTC URL changed from `fut_cot_txt_{year}.zip` → `deacot{year}.zip`
- Column names changed from underscore format to human-readable (e.g. `"Noncommercial Positions-Long (All)"`)
- GBPUSD missing because GBP contract renamed from "BRITISH POUND STERLING" to "BRITISH POUND"
- Double download on startup fixed: `_last_cot_refresh = time.monotonic()` after seed

### Step 11 — Economic Calendar / News Filter ✅ DONE
**Files:** `data/news_filter.py` (new), `core/config.py`, `engine.py`, `data/news_events.json` (auto-generated)

Zero-maintenance news blackout filter — pauses all signal entry 15 min before/after high-impact events.

**Coverage (fully automatic, no manual updates needed):**
1. US NFP — first Friday every month at 13:30 UTC (built-in, no network call)
2. FOMC rate decisions — scraped weekly from `federalreserve.gov`
3. BOE rate decisions — scraped weekly from `bankofengland.co.uk`
4. ECB rate decisions — scraped weekly from `ecb.europa.eu`

**Auto-refresh:** `refresh_central_bank_calendar()` checks `_refreshed_at` sentinel in JSON,
re-scrapes if older than 7 days. Runs on startup and weekly. `news_events.json` auto-updates —
no manual maintenance ever needed.

**DST handling:** `_us_is_dst()` / `_eu_is_dst()` use `calendar.monthrange` to find nth
Sundays correctly (avoids ValueError on months with 31 days).

**B6 fix (amend_stop price scale):** `amend_stop()` now multiplies `new_stop × price_scale`
before sending to IG. EUR/USD (price_scale=10000) correctly sends 11450 not 1.1450.
Rounding: 1 dp if price_scale > 1, 5 dp otherwise.

**Config:** `NEWS_FILTER_ENABLED`, `NEWS_PAUSE_MINUTES=15`, `NEWS_EVENTS_FILE`, `NEWS_CALENDAR_REFRESH_DAYS=7`, `FMP_API_KEY`
**Tests:** 17 new tests; total 116/116 passing

### Step 12 — Dashboard v2 + Backtesting Page ✅ DONE

**Files:** `dashboard/app.py`, `dashboard/static/index.html`, `dashboard/static/backtest.html` (new)

**Dashboard v2 additions (live dashboard at `/`):**
- Header: NEWS pill (clear/paused), next event countdown ("Next event: 2h14m")
- Quote cards: regime tag + last signal readout per pair
- Filter status bar: per-pair Regime / COT Bias / Session / News columns
- Session & Risk card: updated to correct values (1% risk, 4%/8% soft/hard DD limits)
- Equity card: Today's PnL row (realised closed trades since UTC midnight)
- Trade Statistics card: win rate, profit factor, avg win, avg loss, W/L count (colour-coded)
- Equity curve: full-width, 260px tall (was 160px squashed in 3-column row)
- Open positions: regime tag shown on each position card

**Backtesting page at `/backtest`:**
- Three view modes: Hybrid (regime-switching) / Mean Reversion Only / Side-by-Side Comparison
- Per-pair stat cards: trades, win rate, total return, max drawdown, profit factor, final balance
- Per-pair equity curves (Chart.js), overlaid in compare mode (hybrid coloured, baseline dashed grey)
- Comparison table with green/red better/worse highlighting across all pairs
- Filterable trade log: by pair, result (win/loss/timeout), strategy (MR/TF)
- Results cached 5 minutes; "Run Backtest" button forces refresh
- "← Live Dashboard" nav link; "Backtest" nav link on main dashboard

**API additions to `/api/state`:**
- `regime` per pair (live OHLC → `detect_market_regime`)
- `cot_bias` per pair (`CotBias.get_bias`)
- `last_signal` per pair (most recent signal from DB)
- `trade_stats` (win rate, PF, avg win/loss across all closed trades)
- `today_pnl` (realised PnL since UTC midnight)
- `news_active` (boolean: is engine currently paused for news)
- `next_event` (ISO datetime of next scheduled high-impact event)

**New API endpoint `/api/backtest`:**
- Runs `run_backtest()` for all 4 pairs, baseline and hybrid
- Downsamples equity curves for fast transfer
- Adds timestamps to trades (bar index → actual bar datetime)
- Caches 5 minutes

### Step 13 — Telegram Alerts ✅ DONE
**Files:** `data/notifier.py` (new), `core/config.py`, `engine.py`

Real-time Telegram notifications — never raises, silently no-ops if unconfigured.

**Alert triggers:**
- ✅ Engine started — pairs, mode (DRY RUN / LIVE), session window, live balance
- 📈/📉 Trade open — pair, direction, entry/stop/target
- 🔴 Trade closed — pair + estimated P&L (mid-session sync)
- ⚠️ Daily loss limit hit — once per day (deduplicated to avoid spam)
- 🚨 Hard drawdown halt — balance + halt message
- 🚨 Auth failure on startup
- 🚨 Engine crash — exception type + restart prompt
- 🛑 Normal stop — clean shutdown

**Setup:** Add to `.env`:
```
TELEGRAM_TOKEN=<bot token from @BotFather>
TELEGRAM_CHAT_ID=<your numeric chat ID>
```
Find chat_id: message your bot → `https://api.telegram.org/bot<TOKEN>/getUpdates`

**Config:** `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ENABLED`
**Tests:** 8 new tests; total 124/124 passing

---

### Step 14 — Daily Performance Report ✅ DONE
**Files:** `data/reporter.py` (new), `core/db.py`, `engine.py`

Automated daily summary sent via Telegram after session close (16:00 UTC / 18:00 SAST).

**Contents:** trades today (wins/losses), today P&L, running win rate, account balance, drawdown vs initial.

**DB additions:** `today_closed_trades()`, `all_time_stats()` in `core/db.py`.

**Trigger:** fires once per day when `now.time() >= SESSION_END_UTC` and date has not already been reported.

---

### Step 17 — Yahoo Finance Historical Data ✅ DONE
**Files:** `data/yahoo_fetcher.py` (new), `backtest.py`, `requirements.txt`

Free 2-year hourly FX data for backtesting — no IG quota consumed.

**Usage:**
```
python backtest.py --yahoo              # all 4 pairs, ~2yr data
python backtest.py --yahoo --symbol EURUSD
```

**Backtest enhancements added alongside:**
- Session filter: only generates signals during 12:00–16:00 UTC (matches live engine)
- 2-pip round-trip spread cost deducted from every trade P&L
- `--bars` defaults to all available bars (10,000) for Yahoo, 1,500 for IG

**Results (EURUSD, 2yr Yahoo, with BB — Step 18):**
- Mean reversion: 115 trades, 26.1% win rate, +3.9% return
- Note: backtester does NOT model MTF/COT/news filters → live win rate should be higher

---

### Step 18 — Bollinger Bands Mean Reversion Upgrade ✅ DONE
**Files:** `core/config.py`, `strategy/indicators.py`, `strategy/mean_reversion.py`, `backtest.py`, `test_all.py`

Replaced VWAP with Bollinger Bands (±2σ) as the price-position filter in mean reversion.

**Why:** With zero-volume FX data, VWAP degrades to a 20-bar rolling average — true ~50% of bars, barely filtering anything. BB ±2σ triggers only at genuine statistical extremes (~5% of bars), dramatically improving signal quality.

**New signal logic:**
- LONG:  `RSI < 30 AND close <= BB_lower`
- SHORT: `RSI > 70 AND close >= BB_upper`

**New config constants:** `MR_BB_PERIOD=20`, `MR_BB_STD_DEV=2.0`
**New function:** `bollinger_bands(close, period, num_std)` in `strategy/indicators.py`
**`_vwap` kept** — not removed, may be useful for reference.

**Backtest improvement:** Win rate 21% → 26.1% (EURUSD, 2yr Yahoo data)
**Tests:** 23 new tests; total 176/176 passing

---

## Revisit After More Data

### Timeout Trade Behaviour
Current backtest (only 6 trades/pair) shows ~50% timeout rate — too small a sample to conclude anything.
After pulling 3000 bars (`python backtest.py --fetch --bars 3000`), check:

- What % of all trades are timeouts?
- Are timeouts net positive or negative in aggregate?
- Which pairs / strategies (MR vs TF) produce the most timeouts?

**Options to consider depending on what the data shows:**

| Scenario | Action |
|----------|--------|
| Timeouts mostly positive | Accept them — they're helping |
| Timeouts mostly negative | Reduce `MAX_HOLD_BARS` (currently 20) |
| Too many timeouts on TF | Increase `TF_TARGET_ATR_MULT` — trend target too far |
| Too many timeouts on MR | Reduce `MR_TARGET_ATR_MULT` from 3.0 → 2.0 (closer target, faster close) |
| Timeouts near breakeven | Add breakeven rule: move stop to entry once trade is +1R profitable |

**Config to tune:** `MAX_HOLD_BARS` in `backtest.py` (currently 20 bars = 20 hours on 1h data)

---

### RSI Threshold Tuning
Yahoo Finance backtest (18 months, session-filtered, 2pip spread) shows **~21% win rate** — below the 33% needed for 2:1 R/R profitability. Current thresholds: `MR_RSI_OVERSOLD=30`, `MR_RSI_OVERBOUGHT=70`.

**After 2 weeks of demo trading, check live win rate:**
- If **≥ 33%** → parameters are fine; historical period (2024–2026 USD trending cycle) was just unfavourable for MR
- If **< 33%** → tighten RSI thresholds to only trade more extreme setups:
  - `MR_RSI_OVERSOLD: 30 → 25`
  - `MR_RSI_OVERBOUGHT: 70 → 75`
  - Re-run `python backtest.py --yahoo` and check if win rate improves
  - Trade-off: fewer signals, but higher conviction entries

---

## Pending Issues (Low Priority)

| # | Issue | File | Priority |
|---|-------|------|----------|
| B7 | `upsert_ohlc` return value counts attempted rows not inserted | `core/db.py` | LOW |
| B8 | Equity table grows forever (~960 rows/day) | `core/db.py` | LOW |
| M6 | No SQLite backup mechanism | ops | LOW |
| M7 | Pip values for USDCHF/GBPJPY are hardcoded approximations (5–10% off) | `core/config.py` | LOW |

---

## Upcoming Steps

### Step 15 — Walk-Forward Validation
**Priority: High (before real money)**

Run the backtest across rolling time windows (e.g. 6 months in-sample, 1 month out-of-sample, step 1 month)
to check whether the strategy parameters hold up out-of-sample.

- Detect if current parameters are overfit to the cached training period
- If out-of-sample performance degrades sharply vs in-sample → re-examine parameters
- Tools: extend `backtest.py` with `--walk-forward` flag
- Deferred until after 2-week demo run

### Step 16 — Live Account Migration Checklist
**Priority: High (before going live)**

Before switching `IG_DEMO=false`:
- [ ] Complete 2-week demo run, evaluate live win rate vs 33.3% threshold
- [ ] Run backtest with minimum 500+ trades per pair
- [ ] Confirm walk-forward results acceptable (Step 15)
- [ ] Verify all 176 tests pass on live config
- [ ] Set initial live risk lower: `RISK_PER_TRADE=0.005` (0.5%) for first 2 weeks
- [ ] Set `HARD_DRAWDOWN=0.05` (5%) for live account (tighter than demo 8%)
- [ ] Create a separate live DB (`data/forex_engine_live.db`) — never share with demo
- [ ] Verify `amend_stop` price scaling works correctly on live prices
- [ ] Confirm Telegram alerts working before going live
- [ ] Have a manual kill-switch procedure documented

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

### Fix 5 — IG Minimum Stop Distance Guard
Added guard in `engine.py` after signal recalculation:
- Reads `min_stop_pips` from live quote
- Widens stop to `min_stop_pips × MIN_STOP_BUFFER (1.1)` if too close
- Adjusts target to maintain 2:1 R/R

### Fix 6 — All Hardcoded Values → config.py
28+ magic numbers removed from `engine.py`, `risk/guard.py`, `core/ig_client.py`.

### Fix B6 — amend_stop Price Scale (applied in Step 11)
`amend_stop()` now sends `raw_stop = round(new_stop * price_scale, decimals)`.
EUR/USD: sends 11450 not 1.1450. Other pairs unaffected (price_scale=1).

---

## Master Test Suite

**File:** `test_all.py`
**Run:** `python test_all.py`
**Coverage:** 176 tests across Steps 1–18
**Pass condition:** All tests pass before merging any change.

Last run: 2026-03-24 — **176/176 PASSED**

---

## Parameter Change History

All changes applied on 2026-03-24 based on best-practices comparison vs industry standards.

| Parameter | Original | Changed To | Reason |
|-----------|----------|------------|--------|
| `MR_RSI_OVERSOLD` | 35.0 | **30.0** | Standard oversold threshold. 35 fired too often on shallow dips. |
| `MR_RSI_OVERBOUGHT` | 65.0 | **70.0** | Standard overbought. 65 fired on minor retracements. |
| `MR_STOP_ATR_MULT` | 0.8 | **1.5** | 0.8×ATR stop was inside the noise band. 1.5×ATR is minimum viable for 1h forex. |
| `MR_TARGET_ATR_MULT` | 1.6 | **3.0** | Maintains 2:1 R/R with new stop. |
| `TF_FAST_EMA_PERIOD` | 9 | **12** | 12/26 is the canonical MACD pair — decades of empirical support. |
| `TF_SLOW_EMA_PERIOD` | 21 | **26** | Paired with fast=12. |
| `TF_STOP_ATR_MULT` | 0.8 | **2.0** | Trend trades need room. 2×ATR is standard for trend-following. |
| `TF_TARGET_ATR_MULT` | 1.6 | **4.0** | 4/2 = 2:1 R/R. Allows trend to develop. |
| `SOFT_DRAWDOWN` | 0.02 | **0.04** | 2% triggered too aggressively on normal intraday variance. |
| `HARD_DRAWDOWN` | 0.04 | **0.08** | 4% halt too conservative. 8% is industry standard. |
| `TRAILING_ATR_MULT` | 0.8 | **1.2** | 0.8×ATR trailing stop closed winners too early. |
| `REGIME_ATR_SPIKE_MULT` | 1.5 | **2.0** | 1.5× paused on routine spikes. 2.0× only triggers on genuine events. |
| `HISTORY_BARS` | 500 | **1000** | 500 bars ≈ 21 days. 1000 bars ≈ 42 days — better indicator warm-up. |
| `RISK_PER_TRADE` | 0.005 | **0.01** | Increased to 1% (still conservative; industry standard for funded accounts). |

---

## IG-Imposed Constraints (Not Tunable)

- **Minimum deal size**: 1 contract (Fix 3 handles with `math.ceil`)
- **Minimum stop distance**: Per-instrument, read from `dealingRules.minNormalStopOrLimitDistance` (Fix 5)
- **Order type**: MARKET for instant fill
- **Stop/limit on new orders**: `stopDistance`/`limitDistance` in pips (Fix 2)
- **Stop/limit on amendments**: Absolute `stopLevel` (Fix B6)
- **Daily OHLC data allowance**: Limited on demo — 403 errors after heavy seeding; resets midnight UTC

---

## Instruments Wired to Demo Account

| Pair | Epic | Price Scale | Pip Size | Pip Value (USD) |
|------|------|-------------|----------|-----------------|
| EUR/USD | CS.D.EURUSD.CFD.IP | 10000 | 0.0001 | $10.00 |
| GBP/USD | CS.D.GBPUSD.CFD.IP | 1 | 0.0001 | $10.00 |
| USD/CHF | CS.D.USDCHF.CFD.IP | 1 | 0.0001 | $12.50 |
| GBP/JPY | CS.D.GBPJPY.CFD.IP | 1 | 0.01 | $6.30 |

Min stop distances (from IG dealingRules as of 2026-03-24):
- EUR/USD: 6.0 POINTS
- GBP/USD: 12.0 POINTS
- USD/CHF: 4.0 POINTS
- GBP/JPY: 4.0 POINTS

---

## File Map

```
forex-engine/
  engine.py                        — main loop, strategy switcher, all risk gates wired
  backtest.py                      — vectorised backtester (baseline vs hybrid)
  test_all.py                      — master test suite (116 tests)
  core/
    config.py                      — ALL parameters (edit here only)
    db.py                          — SQLite helpers (all tables + queries)
    ig_client.py                   — IG REST API wrapper
  strategy/
    indicators.py                  — shared atr(), rsi(), bollinger_bands() (Step 18)
    mean_reversion.py              — RSI + Bollinger Bands signal (Step 18: replaced VWAP)
    trend_following.py             — EMA crossover strategy
    regime_detection.py            — ADX+ATR regime classifier
    mtf_filter.py                  — 5m confirmation filter
    cot_bias.py                    — COT 52-week index bias filter
  risk/
    guard.py                       — SessionGate, SpreadFilter, PositionSizer,
                                     EquityGuard, DailyLossGuard, TrailingStopManager,
                                     CorrelationGuard
  data/
    fetcher.py                     — fetch_live_quote, seed_history, refresh_bars
    cot_fetcher.py                 — CFTC COT downloader + parser
    news_filter.py                 — news event cache, central bank scraper, is_news_window
    news_events.json               — auto-generated by scraper (FOMC/BOE/ECB dates)
  execution/
    gateway.py                     — ExecutionGateway, submit()
  dashboard/
    app.py                         — FastAPI backend (/api/state, /api/backtest)
    static/
      index.html                   — live dashboard (quotes, filters, equity, positions)
      backtest.html                — backtesting page (stats, curves, trade log)
  logs/
    engine.log                     — rotating file log (5MB × 3)
    alerts.log                     — auth failures + hard drawdown events
  data/
    forex_engine.db                — SQLite (trades, signals, equity, OHLC, COT, quotes)
  memory/
    project_upgrade_roadmap.md     — this file
```

---

## Current Engine Status (2026-03-24)

- **Mode:** `--live` = REAL ORDERS on IG DEMO account Z69JGB (fake money, real prices)
- **Balance:** $20,272.00
- **Session:** 12:00–16:00 UTC (14:00–18:00 SAST)
- **Strategy:** Hybrid regime-switching — RANGING → mean reversion (RSI+BB), TRENDING → EMA crossover
- **Signal filter:** RSI < 30 AND close ≤ BB_lower (long) / RSI > 70 AND close ≥ BB_upper (short)
- **COT data:** 208 rows (2025) + 44 rows (2026) loaded for all 4 pairs
- **News events:** 29 events loaded (NFP + 26 central bank)
- **OHLC:** 477 hourly + 524 5m bars cached per pair
- **Tests:** 176/176 passing
- **Scheduler:** Windows Task Scheduler — `ForexEngineDemo` fires `start_engine.bat --live` at 14:00 SAST Mon–Fri
- **Telegram:** ✅ Startup alert, trade alerts, daily report, crash/stop alerts all wired
- **2-week demo run:** Started 2026-03-24. Evaluate live win rate vs 33.3% threshold at end.
- **After demo:** If win rate < 33% → tighten RSI to 25/75 and re-backtest. If ≥ 33% → proceed to Step 16 live checklist.
