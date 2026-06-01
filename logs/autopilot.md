# Autopilot Changelog

Append-only. Every autonomous run adds an entry. Most recent at the bottom.

---

## 2026-04-14T18:30:00Z — initialization
- Autopilot infrastructure installed by human collaborator.
- Baseline 4 tuning changes committed in `234f7f6`:
  - mean_reversion: BB near-touch buffer 0.15*ATR
  - trend_following: pullback re-entry 0.3*ATR
  - sentiment: BLOCK_THRESHOLD 0.5 → 0.75
  - engine: strategy modules at DEBUG
- Engine restarted 2026-04-14T18:18:51Z, running cleanly post-session.
- First autonomous run expected: tomorrow 2026-04-15 at ~11:30 UTC (morning) and ~17:00 UTC (evening).

## 2026-04-14T19:00:00Z — evening (Day 1, first autonomous run)
- Signals: 0 | Trades: 0 | P&L: $0.00 | Balance: $1,989.84
- Engine ran during session 12:00–16:00 UTC; no crashes or Tracebacks.
- SPOTCRUDE blocked all session by spread (5.4–7.4 pips > 5.0 limit).
- Sentiment parse failures for GBPUSD and USDCHF at 14:00–15:01 UTC (5 refresh cycles, ~1h15m). Claude API returned malformed JSON (unterminated string). Scores recovered from 15:16 UTC onwards.
- GBPJPY sentiment: bearish 0.70 all session. XAUUSD/SPOTCRUDE: bearish 0.80 early, then switched. GBPUSD/USDCHF: bullish 0.70 once recovered.
- No strategy signal lines (Signal:, rejected, BLOCKED) seen at all — entry conditions not met on Day 1.
- Decision: NO TUNING. Rubric requires 48h of zero signals before loosening. Too early to tune on first session.
- Proposal logged: sentiment parse failure for GBPUSD/USDCHF (see autopilot_proposals.md).
- Telegram daily summary sent.

## 2026-04-14T19:30:00Z — evening (Day 1, manual re-check)
- Second evening check triggered manually (session close re-review).
- Signals: 0 | Trades: 0 | P&L: $0.00 | Balance: $1,989.84
- Engine running cleanly — two python.exe processes confirmed, last log activity at 18:29 UTC.
- No crashes, no Tracebacks since 2026-04-14 engine start. Old errors in log are from 2026-03-31 deployment only.
- Regime: GBPUSD/USDCHF/GBPJPY/SPOTCRUDE TRENDING (ADX 46–57); XAUUSD RANGING (ADX 15.2).
- Sentiment parse failures confirmed: GBPUSD/USDCHF failed 14:00–15:01 UTC (5 cycles, ~1h15m). Scores recovered 15:16 UTC. Already logged in proposals.
- SPOTCRUDE spread-blocked entire session (5.4–7.4 pips vs 5.0 limit). Already in proposals.
- Decision: NO TUNING. 48h zero-signal threshold requires two full sessions before loosening. Only one session complete.
- Telegram daily summary sent.

## 2026-04-14T20:00:00Z — evening (Day 1, third check)
- Signals: 0 | Trades: 0 | P&L: $0.00 | Balance: $1,989.84
- Engine running cleanly — two python.exe processes (PIDs 6028, 3516), last log activity 18:29 UTC.
- No crashes, no Tracebacks. Engine gracefully shut down at 17:56:42 UTC (shutdown signal), restarted at 18:18:51 UTC.
- Engine's built-in daily report already sent at 18:19:08 UTC (197 chars).
- DB confirms: 0 total trades, 0 wins, 0 losses, 0 open positions. Engine has generated zero signals across all 26,520 log lines since 2026-03-31 deployment (~14 days).
- Regime: GBPUSD/USDCHF/GBPJPY/SPOTCRUDE TRENDING (ADX 46–57); XAUUSD RANGING (ADX 15.2).
- Sentiment post-restart (17:51 UTC): all five pairs bullish at 0.70 confidence — sentiment gate is open.
- Decision: NO TUNING. Still Day 1 of autopilot; 48h condition not elapsed since init (2026-04-14T18:30Z). Tomorrow's evening run (2026-04-15) will trigger the loosening if session 2 also has zero signals. Prime suspect: compound of strict sentiment threshold (0.75) + TRENDING regime blocking MR + SPOTCRUDE spread-blocking.
- Autopilot Telegram daily summary sent.

## 2026-04-15T13:30:00Z — morning (Day 2)
- Engine: running — two python.exe processes (PIDs 6028, 3516). Last log activity 13:24 UTC.
- MT5: authenticated (last confirmed at startup 2026-04-14 18:18:56 UTC). Bar fetches continuing cleanly through session open.
- Session: already open (12:00 UTC). Bars being fetched for all 5 pairs. No crashes, no Tracebacks, no ERRORs in log.
- DB: 0 total trades, 0 open positions, $0.00 P&L, balance $1,989.84. Zero signals since deployment (2026-03-31).
- Decision: NO TUNING. Morning cycle — tuning is reserved for evening runs only.
- Telegram morning all-good sent.

## 2026-04-15T18:00:00Z — evening (Day 2)
- Engine: running — two python.exe processes (PIDs 6028, 3516). Last log activity 18:30 UTC (bar fetch post-session).
- No crashes, no Tracebacks, no ERRORs today.
- Session (12:00–16:00 UTC): 1 signal generated — trend_following GBPUSD LONG @ 1.35601. Trade opened at 14:07:53 UTC.
- 1 trade currently open: GBPUSD LONG (unrealised). 0 closed trades. Realised P&L: $0.00. Balance: $1,989.84.
- Post-session (17:49–17:59 UTC): USDCHF trend SHORT signals generated repeatedly but blocked by correlation guard (USD_SHORT group at 1/1). This is correct — GBPUSD LONG already occupies the USD_SHORT slot.
- Sentiment: one Claude parse failure at 17:49:57 UTC (recurring issue, already in proposals). All other pairs scoring fine.
- Tuning rubric: engine is working and traded — 48h zero-signal condition does NOT apply. 0 closed trades means no win-rate analysis possible. No crashes. No tuning warranted.
- Decision: NO TUNING. Engine healthy; first trade in the book; correlation guard functioning as designed.
- Telegram daily summary sent (184 chars).

## 2026-04-16T11:30:00Z — morning (Day 3)
- Engine: running — two python.exe processes (PIDs 6028, 3516). Last log activity 13:05 UTC (within active session).
- MT5: authenticated — bar fetches continuing cleanly for all 5 pairs with no auth errors.
- Session: already open (12:00 UTC). Engine fetching bars normally; no crashes, Tracebacks, or ERRORs in log.
- DB: 1 closed trade (GBPUSD LONG, closed by broker at 23:01:59 UTC 2026-04-15, PnL $0.00). 0 open positions. Balance ~$1,989.84.
- Decision: NO TUNING. Morning cycle — tuning reserved for evening runs only.
- Telegram morning all-good sent.

## 2026-04-16T18:45:00Z — evening (Day 3)
- Engine: running — two python.exe processes (PIDs 6028, 3516). Last log activity 18:41 UTC (post-session bar fetch).
- No crashes, no Tracebacks, no ERRORs since last run.
- Session (12:00–16:00 UTC): 0 signals generated. 0 trades. Realised P&L: $0.00. Balance: $1,989.84.
- Regime: GBPUSD TRENDING (ADX 20.9 vs threshold 20), USDCHF TRENDING (ADX 20.1 vs threshold 20). GBPJPY/XAUUSD/SPOTCRUDE RANGING throughout session. ADX barely above threshold — naturally quiet day.
- Sentiment: GBPUSD/GBPJPY/XAUUSD bullish (0.70), USDCHF bullish (0.60–0.70), SPOTCRUDE bearish (0.80). One post-session parse failure at 17:50 UTC (recurring issue, already in proposals).
- DB: 1 total closed trade (GBPUSD LONG, PnL $0.00). 0 open positions.
- Post-session: COT refreshed at 18:32 UTC. Engine sent daily report at 18:00:30 UTC.
- Tuning rubric: (1) Zero-signal 48h rule N/A — signal generated yesterday 2026-04-15. (2) Win-rate analysis N/A — only 1 closed trade, need ≥10. (3) No crashes.
- Decision: NO TUNING. Market regime was simply weak today (ADX 20–21 vs threshold 20); filters working correctly. Insufficient trade history for statistical tuning decisions.
- Telegram daily summary sent.

## 2026-04-17T13:15:00Z — morning (Day 4)
- Engine: running — two python.exe processes (PIDs 6028, 3516). Last log activity 13:06 UTC (HOUR bars for GBPUSD/USDCHF/GBPJPY).
- MT5: authenticated — bar fetches running cleanly for all 5 pairs, no auth errors.
- Session: already open (12:00 UTC). Engine fetching bars normally; no crashes, Tracebacks, or ERRORs in log overnight or this morning.
- DB: 1 total closed trade (GBPUSD LONG, PnL $0.00). 0 open positions. Balance ~$1,989.84.
- Decision: NO TUNING. Morning cycle — tuning reserved for evening runs only.
- Telegram morning all-good sent.

## 2026-04-17T18:00:00Z — evening (Day 4)
- Engine: running — two python.exe processes (PIDs 6028, 3516). Last log activity 18:41 UTC (post-session bar fetch + COT refresh).
- No crashes, no Tracebacks, no ERRORs during or after session.
- Session (12:00–16:00 UTC): 1 signal fired — trend_following XAUUSD SHORT @ 4804.91 (12:06:57 UTC). Trade opened, stopped out at 4820.81 at 12:31:31 UTC (~25 min). PnL: -$0.16.
- Post-stop: 20+ repeat XAUUSD SHORT signals generated throughout session (14:31–15:00+ SAST), all blocked by sentiment (bullish 0.80 confidence). Sentiment correctly identified the bullish pressure that triggered the stop.
- SPOTCRUDE spread-blocked entire session (5.4 pips > 5.0 limit) — recurring issue, already in proposals.
- DB: 2 total closed trades (GBPUSD LONG $0.00 on 2026-04-15, XAUUSD SHORT -$0.16 today). 0 open positions. All-time PnL: -$0.16.
- Regime: GBPUSD TRENDING (ADX 24.1), USDCHF TRENDING (ADX 29.1), GBPJPY RANGING (ADX 19.5), GBPJPY TRENDING (ADX 21.2), XAUUSD TRENDING (ADX 26.1 > 25 threshold), SPOTCRUDE TRENDING (ADX 24.1).
- Sentiment post-session: GBPUSD bullish 0.70, USDCHF bearish 0.80, XAUUSD bullish 0.80, SPOTCRUDE bullish 0.70.
- Tuning rubric: (1) Zero-signal 48h rule N/A — signal fired today. (2) Win-rate analysis N/A — only 2 closed trades, need ≥10. (3) No crashes.
- Decision: NO TUNING. Sentiment filter worked correctly — it blocked continued shorts after the stop, consistent with the bullish move that caused the loss. Too few trades for statistical decisions.
- Telegram daily summary sent (True).

## 2026-04-18T19:00:00Z — evening (Day 5, Saturday)
- Engine: running — two python.exe processes (PIDs 6028, 3516). Last log activity 18:58 UTC (post-session bar fetch).
- No crashes, no Tracebacks, no ERRORs. Engine's built-in daily report sent at 18:00:26 UTC (197 chars).
- Today is Saturday — forex market closed during 12:00–16:00 UTC session window. No live trading expected.
- Session activity: 610 bar-fetch log entries during session window; 0 signal lines, 0 trade lines, 0 error lines. COT refreshed hourly (12:43, 13:43, 14:43, 15:44 UTC).
- DB: 2 total closed trades, 0 wins, 2 losses. All-time PnL: -$0.16. 0 open positions. Balance: ~$1,989.84.
- Last signal: Friday 2026-04-17 at 12:06:57 UTC (~31h ago). 48h zero-signal threshold NOT yet met.
- Tuning rubric: (1) Zero-signal 48h rule N/A — last signal 31h ago, and today is a weekend non-trading day. (2) Win-rate analysis N/A — only 2 closed trades, need ≥10. (3) No crashes.
- NOTE for Monday: if the 2026-04-20 session produces zero signals, that will be ~79h since last signal (>48h threshold). Prime suspects in order: (a) sentiment threshold 0.75, (b) MR BB_NEAR_TOUCH_ATR 0.15, (c) trend pullback distance. Next evening run should loosen ONE by ≤25% if Monday session is also silent.
- Decision: NO TUNING. Weekend non-trading day; rubric conditions not met.
- Telegram daily summary sent.

## 2026-04-19T19:00:00Z — evening (Day 6, Sunday)
- Engine: running — two python.exe processes (PIDs 6028, 3516). Last log activity 18:55 UTC (post-session bar fetch).
- No crashes, no Tracebacks, no ERRORs. Engine's built-in daily report sent at 18:00:12 UTC (197 chars).
- Today is Sunday — forex market closed. No live trading expected or observed.
- Session activity: bar fetches running cleanly for all 5 pairs throughout the day. COT refreshed at 17:51 UTC and 18:51 UTC. 0 signals, 0 trades.
- DB: 2 total closed trades (0 wins, 2 losses). All-time PnL: -$0.16. 0 open positions. Daily PnL: $0.00. Balance: ~$1,989.84.
- Last actual signal: Friday 2026-04-17 at 12:06:57 UTC (~55h ago). Technically past the 48h threshold, but both elapsed days were non-trading weekend days. Counting weekend silence against the signal-frequency gate is not meaningful.
- Tuning rubric: (1) 48h zero-signal rule: threshold elapsed on clock time, but weekend days excluded from meaningful analysis. Prior run (Day 5) correctly noted to wait for Monday's session result before acting. (2) Win-rate analysis N/A — only 2 closed trades, need ≥10. (3) No crashes.
- Decision: NO TUNING. Weekend non-trading day. Monday 2026-04-20 session is the definitive test: if it produces zero signals, the 48h loosening rule will fire. Prime suspect remains sentiment threshold 0.75 — loosen to 0.62 (−17%, within ±25% rail) if Monday is silent.
- Telegram daily summary sent (True).

## 2026-04-19T20:35:00Z — weekly (Week 1 review)

### Engine health
- Engine: running — last log activity 20:25 UTC. No crashes, no Tracebacks, no ERRORs across entire week.
- DB: 2 total closed trades, 0 wins, 2 losses, all-time PnL -$0.16. 0 open positions. Balance: ~$1,989.84.

### Week 1 trade review (2026-04-14 to 2026-04-19)
- Trade 1: GBPUSD LONG @ 1.35605, opened 2026-04-15 14:07 UTC. Closed 2026-04-15 21:01 UTC by broker (after-hours). PnL $0.00.
- Trade 2: XAUUSD SHORT @ 4804.91, opened 2026-04-17 12:06 UTC. Stopped out 12:31 UTC (25 min). PnL -$0.16.
- Both were trend_following signals. Zero mean_reversion signals (market predominantly TRENDING — correct filter behaviour).
- Post-stop Day 4: 20+ XAUUSD SHORT repeat signals CORRECTLY blocked by sentiment (bullish 0.80 > 0.75 threshold). Price continued up — sentiment filter vindicated.
- SPOTCRUDE spread-blocked all 5 trading sessions (5.4–7.4 pips > 5.0 limit). 0 SPOTCRUDE trades possible.

### Research agent run
- `python research_agent.py` ran 20:30 UTC (Unicode issue on first attempt; resolved with PYTHONIOENCODING=utf-8).
- Key findings: (1) Citi report on compressed-volatility forex regime — may explain low EMA crossover frequency. (2) Academic paper validating hybrid MR+TF for commodity futures (consistent with our design). (3) MT5 Python package 5.0.35 available (minor upgrade).
- Telegram digest sent by research_agent.py directly (988 chars).

### Sentiment threshold re-analysis
- Prior runs suspected 0.75 as "prime suspect" for zero signals. After deep review: Day 3 zero signals were due to EMA crossover not firing (ADX 20.9, weak trend), NOT sentiment blocking (0.70 < 0.75). The 0.75 threshold is performing correctly.
- Updated "prime suspect" for Monday: if 0 signals, investigate TF_PULLBACK_ATR_DIST (0.3 ATR) not sentiment threshold.

### Tuning decision
- Rubric trigger conditions evaluated: (1) 48h zero-signal — not met on trading days. (2) Win-rate — only 2 trades, need ≥10. (3) Crashes — none.
- Decision: NO TUNING. Doing nothing is correct. Engine is healthy and filters are working as designed.
- 4 proposals written to logs/autopilot_proposals.md.

### Telegram sent
- Sent 1 summary message (weekly).

## 2026-04-20T19:15:00Z — evening (Day 7, Monday — CRASH + RESTART)

### Engine health
- Engine: CRASHED. Log stopped at 12:10 UTC today (10 min into session). Zero log entries from 12:10–19:03 UTC (~7h downtime). Only 1 python.exe process visible (vs normal 2).
- Engine restarted at 19:03 UTC via `nohup python engine.py --live >> logs/engine.log 2>&1 &` from C:/forex-engine. PID 1134.
- Post-restart: "Engine running — polling every 15s" confirmed at 19:03:16 UTC. Bar fetches running for all 5 pairs. No Tracebacks or ERRORs in restart sequence.
- Engine auto-sent daily report at 19:03:29 UTC (196 chars via built-in notifier).

### Session activity (2026-04-20 12:00–16:00 UTC)
- DB: 2 total closed trades, 0 wins, 2 losses, all-time PnL -$0.16. 0 open positions. Daily PnL: $0.00.
- Engine was offline ~12:10–19:03 UTC. Session data is UNKNOWN. Any trades opened before 12:10 UTC may have closed while engine was offline (not recorded in DB).
- Balance discrepancy: engine reports $1,971.05 vs expected ~$1,989.68 (prior balance -$0.16 all-time loss). Unaccounted drop of $18.37. Likely reflects trades closed by MT5 during the 7h outage that our DB never captured.
- Crash was unlogged — no Traceback, ERROR, or CRASHED line in engine.log before the gap. Engine died silently.

### Notes
- start_engine.bat has wrong path for VPS (`C:\Users\jalbe\OneDrive...` does not exist on VPS). stop_engine.bat worked (kills by window title). Manual restart used nohup from correct C:/forex-engine path.
- Prior plan: loosen TF_PULLBACK_ATR_DIST 0.3→0.37 if Monday was silent. CANNOT apply — (a) crash condition → no tuning, (b) session outcome unknown, (c) $18.79 balance drop suggests active trades occurred.

### Tuning rubric
- Crash condition → NO TUNING. Rubric is clear: do not tune in presence of unexplained crash.

### Decision: NO TUNING.

### Actions taken
- Stopped engine (stop_engine.bat, harmless — process was already down).
- Restarted engine via nohup (running cleanly post-restart).
- Sent Telegram crash alert (227 chars).
- Logged crash proposal to autopilot_proposals.md.

### Telegram sent
- Crash alert sent (True, 227 chars): "🚨 ENGINE CRASH — log stopped at 12:10 UTC today, engine was down ~7h. Restarted 19:03 UTC, now running cleanly. Balance $1,971.05 (was $1,989.84, -$18.79 unaccounted — check MT5 for trades closed during outage). No tuning done."
