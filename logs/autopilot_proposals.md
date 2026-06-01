# Autopilot Proposals (Human Review Required)

Ideas the autopilot considered but did not implement, flagged for the owner to review when back.

Format: most recent at the bottom. Each entry has a timestamp, the proposal, the reasoning, and a suggested next step.

---

## 2026-04-14T19:00:00Z — Sentiment parse failures for GBPUSD/USDCHF

**Observation:** During the first trading session (12:00–16:00 UTC), the Claude sentiment module failed to parse its own JSON response for GBPUSD and USDCHF across five consecutive 15-minute refresh cycles (14:00–15:01 UTC). The error is `Unterminated string starting at: line 18 column 18` — Claude's response was cut off mid-JSON. Scores recovered on their own from 15:16 UTC onwards. This is not fatal (engine kept running), but those two pairs lacked a sentiment score for ~75 minutes of the 4-hour session.

**Risk:** If the engine defaults to "neutral" or "blocked" when sentiment is absent, we miss valid trades on two of our most liquid pairs during the outage window.

**Suggested next step:** Check `data/sentiment.py` — find how missing/failed sentiment scores are handled. If `confidence` defaults to 0 and the logic blocks on zero confidence, consider setting a safe default of `neutral (0.5)` rather than `None`. Alternatively, increase the Claude API retry count from 2 to 3 or add a JSON-truncation guard (check that the response ends with `}` before parsing).

---

## 2026-04-14T19:00:00Z — SPOTCRUDE spread too wide for entire session

**Observation:** SPOTCRUDE (crude oil) was skipped on every engine poll during 14:00–16:00 UTC due to spread exceeding the 5.0-pip limit. Spreads ranged from 5.4 to 7.4 pips. This was not a signal issue — the spread check fires before any strategy logic runs.

**Suggested next step:** Check whether 5.0 pips is the right limit for crude oil. Crude typically has wider spreads than forex. If the backtest used a 2-pip spread model for all pairs (see CLAUDE.md M5), the spread limit may need to be asset-specific. Consider a per-asset `MAX_SPREAD_PIPS` config and a wider limit (e.g. 8–10 pips) for SPOTCRUDE, validated against backtest assumptions.

---

## 2026-04-19 — Weekly Research Findings (research_agent.py run 20:30 UTC)

**Context:** First full trading week complete. 2 signals, 2 trades, 0 wins, -$0.16 PnL across 5 trading days. Engine is healthy with no crashes.

### Finding 1 — Trend-following models need recalibration for new volatility regime

**Source:** Citi Global Markets research report, 2026-04-18.
**Observation:** Report identifies a structural shift in forex market volatility (lower realised vol, compressed ATRs). This is consistent with our engine's low signal frequency — EMA crossovers require price momentum that is currently subdued. Our trend signals fire when: (a) ADX > 20, (b) fast EMA crosses slow EMA, AND (c) price pulls back within 0.3 ATR of the crossover level. In low-volatility regimes, price may oscillate near the EMAs without triggering a clean crossover.
**Suggested next step:** After we have ≥10 trades, review whether tightening the ADX threshold (from 20 to 18) could generate more signals in weaker trends, or whether loosening the pullback window (TF_PULLBACK_ATR_DIST 0.3 → 0.35) captures more re-entries. Do NOT change this now — wait for data.

### Finding 2 — Hybrid mean reversion + trend following for commodity futures

**Source:** Journal of Empirical Finance, 2026-04-15.
**Observation:** Academic paper shows promising out-of-sample results for a hybrid strategy on commodity futures — which is exactly our engine's design for XAUUSD and SPOTCRUDE. Our one XAUUSD trade was a short (trend) that got stopped out, with sentiment correctly flagging the bullish move. MR has not fired yet because XAUUSD regime has been RANGING some days but also TRENDING — the ADX threshold (25 for gold vs 20 for forex) may be filtering correctly.
**Suggested next step:** Run the backtester on XAUUSD with a lower ADX threshold (22 vs current 25) to see if there are more valid MR signals in the data.

### Finding 3 — MT5 Python package 5.0.35 available (minor update)

**Source:** MetaTrader5 package, 2026-04-16.
**Observation:** Bug fixes and minor performance improvements. We are likely running an older version.
**Suggested next step:** During a maintenance window (weekend, after verifying engine is stopped), run `pip install --upgrade MetaTrader5` and test connectivity. Low risk.

### Finding 4 — SPOTCRUDE spread blocking (persistent, 5 sessions now)

**Observation:** Every session since deployment (5 trading days), SPOTCRUDE has been spread-blocked (measured 5.4–7.4 pips, limit is 5.0 pips). The limit is configured in `core/config.py` PAIR_CONFIG (denylist for autopilot). This requires human action to change.
**Suggested next step:** Review whether the 5.0 pip limit for SPOTCRUDE reflects the backtest assumptions. If backtest used 2-pip spread for all pairs, then the 5.0 pip live spread is genuinely wider than expected — this may explain why oil was not profitable in backtest (or the spread was not correctly modelled). Consider either: (a) raising limit to 8 pips for SPOTCRUDE in config, or (b) removing SPOTCRUDE from active pairs until spread conditions improve.

### Tuning decision for this weekly run

**NO TUNING applied.** All trigger conditions reviewed:
1. 48h zero-signal rule: not met on trading days (2 signals in 5 trading days; last signal Friday April 17).
2. Win-rate < 40% with ≥10 trades: only 2 trades — insufficient for statistical action.
3. Crashes: none.

**Sentiment threshold re-analysis:** Prior runs suspected the 0.75 threshold as the prime suspect for zero signals. After deeper review: on Day 3 (April 16), GBPUSD sentiment was 0.70 (below 0.75 threshold — NOT blocked by sentiment). The zero signals that day were from the EMA crossover not firing in a weak trend (ADX 20.9). The sentiment threshold is performing correctly. Lowering it would NOT have added signals on Day 3 and WOULD have allowed weaker-conviction trades on Day 4 (when it correctly blocked continued XAUUSD shorts).

**Pre-plan for Monday 2026-04-21:** If the Monday session (12:00–16:00 UTC) also produces zero signals AND ADX for trending pairs is above 20, then consider loosening TF_PULLBACK_ATR_DIST from 0.3 to 0.37 (+23%) rather than the sentiment threshold. The pullback distance is the more likely culprit for missed trend entries in a compressed-volatility environment.

---

## 2026-04-20T19:15:00Z — Engine crash (silent, 7h downtime) + balance discrepancy

**Priority: HIGH — requires human investigation**

**Observation:** Engine stopped writing to log at 12:10 UTC on 2026-04-20 (10 minutes into the trading session). No Traceback, no ERROR, no CRASHED line visible — the process died silently. Log gap: 12:10–19:03 UTC (~7 hours). Engine was restarted by autopilot at 19:03 UTC.

**Balance discrepancy:** Engine reports account balance of $1,971.05 on restart. Prior known balance was ~$1,989.84 (all-time PnL -$0.16 from our DB). The difference of ~$18.37 is unaccounted in our DB. During the 7h downtime, MT5 may have opened and closed positions autonomously (stop-hits, take-profits) that our engine never recorded. The DB will never be updated for those trades since the engine was offline.

**Bat file path wrong on VPS:** `start_engine.bat` hard-codes `C:\Users\jalbe\OneDrive - Ahrhoff Futtergut SA (PTY) Ltd\Github\forex-engine` which does not exist on the VPS. This means the scheduled task restart mechanism may be non-functional on the VPS. Engine was restarted manually via `nohup python engine.py --live &` from `C:/forex-engine`. Fix: update `start_engine.bat` to reference `C:\forex-engine` as the working directory.

**Suggested next steps:**
1. Check MT5 terminal trade history for 2026-04-20 12:00–19:00 UTC to identify what trades closed during the outage and what the actual P&L was.
2. Investigate the crash cause: check Windows Event Viewer for python.exe crashes around 12:10 UTC; check if a scheduled task killed the process; check if memory/disk exhaustion was a factor.
3. Fix `start_engine.bat` path: change `cd /d "C:\Users\jalbe\OneDrive..."` to `cd /d "C:\forex-engine"`.
4. Verify Windows Task Scheduler "Engine" task is configured correctly to auto-restart the engine — if the crash happened silently, the scheduled task should have restarted it but apparently did not.
5. Consider adding a crash watchdog: a separate scheduled task that checks every 5 minutes if `engine.py` is running and restarts it if not.
