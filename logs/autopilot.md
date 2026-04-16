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
