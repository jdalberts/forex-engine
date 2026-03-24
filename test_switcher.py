"""
Smoke test for select_strategy() + detect_market_regime() — run from project root.
No IG connection required. Uses synthetic bars only.
"""
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")

from engine import select_strategy
from strategy.regime_detection import detect_market_regime


def make_bars(n, direction="flat"):
    bars = []
    price = 1.1000
    for i in range(n):
        if direction == "up":
            price += 0.0006
        elif direction == "down":
            price -= 0.0006
        elif direction == "spike" and i > n - 5:
            price += 0.008
        else:
            price += 0.0001 if i % 2 == 0 else -0.0001
        o = price
        h = o + 0.0003
        l = o - 0.0003
        c = o
        bars.append({
            "time": pd.Timestamp("2024-01-01") + pd.Timedelta(hours=i),
            "open": o, "high": h, "low": l, "close": c, "volume": 1000,
        })
    return bars


print("=== Path 1: ranging -> mean_reversion ===")
bars = make_bars(60, direction="flat")
regime = detect_market_regime(bars)
signal = select_strategy(regime, bars)
print(f"  regime={regime}  strategy={signal['strategy'] if signal else 'None (no signal)'}")

print()
print("=== Path 2: trending -> trend_following ===")
bars = make_bars(60, direction="up")   # all-up gives ADX well above 25
regime = detect_market_regime(bars)
signal = select_strategy(regime, bars)
print(f"  regime={regime}  strategy={signal['strategy'] if signal else 'None (no crossover on last bar)'}")

print()
print("=== Path 3: high_volatility -> no trade ===")
bars = make_bars(60, direction="spike")
regime = detect_market_regime(bars)
signal = select_strategy(regime, bars)
print(f"  regime={regime}  signal={signal}")
