"""Quick smoke test for trend_following_signal() — run from project root."""
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")

from strategy.trend_following import trend_following_signal


def make_bars(n, direction="flat"):
    """Generate synthetic OHLCV bars."""
    bars = []
    price = 1.1000
    for i in range(n):
        if direction == "up":
            price += 0.0006
        elif direction == "down":
            price -= 0.0006
        else:
            price += 0.0001 if i % 2 == 0 else -0.0001  # choppy flat

        o = price
        h = o + 0.0003
        l = o - 0.0003
        c = o + (0.0001 if direction == "up" else -0.0001 if direction == "down" else 0)
        bars.append({
            "time": pd.Timestamp("2024-01-01") + pd.Timedelta(hours=i),
            "open": o, "high": h, "low": l, "close": c, "volume": 1000,
        })
    return bars


print("=== Test 1: Flat/choppy market (no crossover expected) ===")
result = trend_following_signal(make_bars(60, direction="flat"))
print("Signal:", result)

print()
print("=== Test 2: Strong uptrend (expect LONG crossover) ===")
# Build bars: first half flat, second half trending up so fast EMA crosses above slow
bars = make_bars(30, direction="flat") + make_bars(30, direction="up")
result = trend_following_signal(bars)
print("Signal:", result)

print()
print("=== Test 3: Strong downtrend (expect SHORT crossover or None) ===")
bars = make_bars(30, direction="flat") + make_bars(30, direction="down")
result = trend_following_signal(bars)
print("Signal:", result)

print()
print("=== Test 4: Not enough bars ===")
result = trend_following_signal(make_bars(10))
print("Signal:", result)
