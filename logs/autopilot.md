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
