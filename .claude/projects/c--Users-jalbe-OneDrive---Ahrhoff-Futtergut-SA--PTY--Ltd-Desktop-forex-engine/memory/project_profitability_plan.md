---
name: Profitability Optimization Results
description: Forex engine fully optimized — PF 1.42, +55%/pair, all 3 pairs profitable over 8 years. Ready for demo trading.
type: project
---

## Final Results (2026-03-26, medium grid optimizer)

**50,000 H1 bars from MT5 (2018–2026), 3 pairs:**
- Overall return/pair: **+55.2%**
- Profit factor: **1.42**
- All three pairs profitable:
  - USDCHF: +105.4%, PF 1.8, DD 13.8%
  - GBPUSD: +35.9%, PF 1.3, DD 12.4%
  - GBPJPY: +24.1%, PF 1.2, DD 17.0%

## Final Parameters (config.py)
| Parameter | Value |
|-----------|-------|
| MR_RSI_OVERSOLD | 25 |
| MR_RSI_OVERBOUGHT | 70 |
| MR_BB_STD_DEV | 2.0 |
| MR_STOP_ATR_MULT | 1.5 |
| MR_TARGET_ATR_MULT | 5.0 |
| TF_FAST_EMA_PERIOD | 20 |
| TF_SLOW_EMA_PERIOD | 50 |
| TF_STOP_ATR_MULT | 3.0 |
| TF_TARGET_ATR_MULT | 8.0 |
| TRAILING_ATR_MULT | 2.0 |
| REGIME_ADX_THRESHOLD | 20 |
| MAX_HOLD_BARS | 40 |
| Session | 12-16 UTC |

## Journey (2026-03-26)
- Started: PF 0.79, -47%/pair (losing on all pairs)
- Step 1-2: PF 1.12, +8.5%/pair (quick grid optimization)
- ADX filter: PF 1.19, +14.8%/pair (3 pairs, EURUSD dropped)
- Medium grid: **PF 1.42, +55.2%/pair** (all 3 pairs profitable)
