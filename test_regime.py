"""Quick smoke test for detect_market_regime() — run from project root."""
import logging
import random
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")

from strategy.regime_detection import detect_market_regime


def make_bars(n, trend=False, spike=False):
    random.seed(42)
    bars = []
    price = 1.1000
    for i in range(n):
        if trend:
            price += 0.0005
        elif spike and i > n - 5:
            price += 0.008
        else:
            price += random.uniform(-0.0003, 0.0003)
        o = price
        h = o + abs(random.gauss(0, 0.0002))
        l = o - abs(random.gauss(0, 0.0002))
        c = random.uniform(l, h)
        bars.append({
            "time": pd.Timestamp("2024-01-01") + pd.Timedelta(hours=i),
            "open": o, "high": h, "low": l, "close": c, "volume": 1000,
        })
    return bars


print("Ranging  :", detect_market_regime(make_bars(60)))
print("Trending :", detect_market_regime(make_bars(60, trend=True)))
print("High vol :", detect_market_regime(make_bars(60, spike=True)))
print("Too few  :", detect_market_regime(make_bars(10)))
