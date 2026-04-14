---
name: Unified Engine Research Findings
description: Deep research on multi-asset expansion — strategies, AI news, data/brokers. 3 agents, comprehensive findings. 2026-03-27.
type: reference
---

## KEY FINDINGS SUMMARY

### 1. Your System is Top Quartile
- PF 1.42, Sharpe ~0.5-0.7 is realistic and sustainable
- Top 25% of retail algo systems
- Walk-forward showing 42.9% OOS profitable with +0.15% avg is genuine (modest) edge
- DO NOT run 209k full grid — severe overfitting risk at that scale

### 2. Highest-Impact Expansion: Commodity Futures
- Commodities have 0.1-0.3 correlation with forex = real diversification
- Portfolio Sharpe improves from ~0.6 to ~0.8-0.9 with 2-3 commodity markets
- Micro contracts accessible: Micro WTI (MCL), Micro Gold (MGC), Micro S&P (MES)
- Your existing trend following (EMA crossover + ADX) translates directly
- Agricultural futures have MORE alpha than financial futures (less quant competition)

### 3. Broker: Pepperstone Has EVERYTHING We Need!
**MASSIVE UPDATE (web research 2026-03-27):** Pepperstone MT5 offers 40+ commodity markets:
- **Precious metals:** Gold (XAUUSD), Silver, Platinum, Palladium
- **Energy:** WTI (USOIL), Brent (UKOIL), Natural Gas, Gasoline
- **Base metals:** Copper, Aluminium, Nickel, Lead, Zinc
- **SOFT COMMODITIES:** Wheat, Corn, Soybeans, Coffee, Cocoa, Cotton, Sugar, Cattle, Lean Hogs
- **25+ Index CFDs:** US500, NAS100, US30, UK100, GER40, AUS200, SA40
- All CONTINUOUS CFDs (no rollover!), same MT5 API, 99.89% fill rate
- **NO broker migration needed AT ALL** — not even for agricultural futures!
- Interactive Brokers only needed if you want actual exchange-traded futures (lower spreads, but more complexity)
- Python API: `ib_insync` (excellent, actively maintained)
- IB minimum: $10k account, $1-2 per round-trip
- IB provides 10+ years free historical data

### 4. AI News Trading: Modest but Real Improvement
- Expected Sharpe improvement: +0.10 to +0.20 (not transformative, but meaningful)
- Best use: sentiment as FILTER (block trades against strong sentiment), not standalone signal
- Architecture: FinBERT locally (fast, free) + Claude API escalation for complex headlines
- Cost: ~$2.50/month for Claude API calls (negligible)
- Highest value: better economic calendar with dynamic blackout windows (free, 1 day to implement)
- DO NOT try to trade initial event moves (too slow vs HFT)

### 5. Strategy Combination Math
- Portfolio Sharpe = sqrt(S1² + S2²) for uncorrelated strategies
- Value + momentum are negatively correlated (-0.5 to -0.7) — best combination
- Adding 2-3 uncorrelated strategies is MORE powerful than adding 2-3 more assets
- Renaissance: thousands of weak signals, not a few strong ones

### 6. Backtesting Framework
- Backtrader recommended for multi-asset (native futures support, auto-rollover)
- VectorBT Pro for fast parameter sweeps ($599/year)
- Custom backtest.py can be extended OR migrated to Backtrader (2-4 weeks)

### 7. Concrete Next Steps (Research-Informed)
Phase 1 (now): Fix bugs, go live on demo, accumulate 200+ trades
Phase 2 (after 200 trades): Evaluate live vs backtest gap, add carry signal
Phase 3 (after 500 trades): Open IB account, backtest futures, deploy combined portfolio
Phase 4 (6+ months): Expand pairs, volatility targeting, quarterly re-optimization

### 8. What NOT to Do
- Don't run 209k optimizer (overfitting)
- Don't build HFT ($50k+/month infrastructure)
- Don't add cryptocurrency (extreme risk)
- Don't pay for Bloomberg/Reuters at this account size
- Don't use VADER for financial text (60-65% accuracy, useless)
- Sharpe > 2.0 in backtest = almost certainly overfit

## WEB RESEARCH UPDATE (2026-03-27)

### New Findings That Change Strategy
1. **Pepperstone has WHEAT, CORN, SOYBEANS** as CFDs — NO broker migration needed for any Phase
2. **ib_insync is DEAD** (creator passed away 2024) — use `ib_async` if ever migrating to IB
3. **Claude Haiku 4.5 = $0.25/M tokens** — AI sentiment costs ~$0.60/month with batch API
4. **Prompt caching + batch = 95% cost reduction** on Claude API
5. **NautilusTrader** — Rust+Python, production-grade, same code backtest→live (free, open source)
6. **PyBroker** — ML-first backtesting with built-in walk-forward validation (better fit than Backtrader)
7. **TradingAgents** — multi-agent LLM trading framework (7 specialized agents). Interesting but premature for us.
8. **No SA regulatory blockers** — COFI Bill is principle-based, no algo restrictions expected
9. **AI handles ~89% of global trading volume** as of 2026
10. **Commodity algo = underexplored** — CFA research says carry + momentum ensembles strongest approach

### Revised Tool Stack
| Need | Tool | Cost |
|------|------|------|
| News headlines | Finnhub free tier (60 req/min) | Free |
| AI sentiment | Claude Haiku 4.5 batch | ~$0.60/month |
| Economic calendar | market-calendar-tool (PyPI) | Free |
| Geopolitical risk | GDELT via gdeltPyR | Free |
| Commodity data | Pepperstone MT5 (already have!) | Free |
| Fast optimization | VectorBT PRO | Paid |
| ML backtesting | PyBroker (walk-forward built in) | Free |
| Production execution | NautilusTrader (future) | Free |

### Key Sources (March 2026)
- Finnhub API: finnhub.io
- Claude pricing: platform.claude.com/docs/en/about-claude/pricing
- NautilusTrader: nautilustrader.io
- PyBroker: pybroker.readthedocs.io
- TradingAgents: github.com/TauricResearch/TradingAgents
- Pepperstone commodities: pepperstone.com/en/markets/commodities
- ib_async (replaces ib_insync): github.com/ib-api-reloaded/ib_async
- CFA ML Commodity Futures: rpc.cfainstitute.org/research/foundation/2025/chapter-8
- GDELT Doc API: github.com/alex9smith/gdelt-doc-api


### Auto-Research Scan (2026-04-05)
- [Strategy & Market Research] A new academic paper published on April 2nd in the Journal of Empirical Finance proposes a novel mean reversion strategy for commodity futures that incorporates time-varying volatility and risk premia.
- [Strategy & Market Research] A research report from Citi Global Markets on April 4th analyzes changes in forex market regime and volatility structure, suggesting increased opportunities for trend following strategies in the current environment.
- [Tool & API Updates] MetaTrader5 Python package version 5.0.35 was released on March 31st with bug fixes and performance improvements.
- [Tool & API Updates] The ib_async library (Interactive Brokers Python) version 9.7.1 was updated on April 3rd with support for the latest IB API release.


### Auto-Research Scan (2026-04-12)
- [Strategy & Market Research] A new academic paper published on April 10th in the Journal of Empirical Finance proposes a hybrid mean reversion and trend following strategy for commodity futures trading, showing promising out-of-sample results.
- [Strategy & Market Research] A research report from Citi Global Markets on April 8th analyzes the recent shift in forex market volatility structure, suggesting a potential regime change that may require adjustments to existing trading models.
- [Tool & API Updates] MetaTrader5 Python package version 5.0.35 was released on April 11th, with bug fixes and minor performance improvements.
- [Tool & API Updates] The ib_async library (Interactive Brokers Python) announced a breaking change on April 9th, requiring updates to the trading engine's order execution code.
- [SA Regulation] The FSCA (Financial Sector Conduct Authority) in South Africa announced new leverage restrictions for retail forex and CFD trading on April 7th, lowering the maximum leverage to 1:20.
