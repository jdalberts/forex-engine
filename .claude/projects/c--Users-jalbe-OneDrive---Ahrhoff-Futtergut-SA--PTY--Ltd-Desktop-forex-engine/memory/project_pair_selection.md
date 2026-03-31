---
name: Pair Selection Decision
description: EURUSD dropped (unprofitable all combos). Trading USDCHF (+40.6%), GBPUSD (+6.2%), GBPJPY (diversification). 2026-03-26.
type: project
---

## Final Pair Selection (2026-03-26)

**Active pairs:**
- **USDCHF: +40.6%, PF 1.6** — strongest performer, keep
- **GBPUSD: +6.2%, PF 1.1** — profitable, keep
- **GBPJPY: -2.3%, PF 1.0** — near breakeven, JPY cross adds diversification (uncorrelated to USD pairs), keep

**Dropped:**
- **EURUSD: REMOVED** — tested 256 parameter combinations on 50,000 bars. Not a single combo was profitable (best: -8.4%). Too efficient for our H1 MR+TF strategy.

## Reasoning
- 3 pairs better than 1 for trade frequency and equity smoothing
- Correlation guard prevents stacking USD-direction trades across USDCHF + GBPUSD
- GBPJPY is a JPY cross (no USD leg) — true diversification
- Without EURUSD drag, portfolio return ~+14.8%/pair average

**How to apply:** Don't re-add EURUSD unless strategy fundamentally changes (e.g., different timeframe, new indicator). Config updated to exclude it.
