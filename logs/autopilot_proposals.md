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
