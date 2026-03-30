"""Quick MT5 connection test — run before starting the engine.

Checks: initialize, login, account balance, EURUSD.a tick.
"""

import sys
import os
from dotenv import load_dotenv

load_dotenv()

LOGIN    = int(os.environ.get("MT5_LOGIN", "0"))
PASSWORD = os.environ.get("MT5_PASSWORD", "")
SERVER   = os.environ.get("MT5_SERVER", "")
PATH     = os.environ.get("MT5_PATH", "")   # optional path to terminal64.exe

print(f"MT5_LOGIN  : {LOGIN}")
print(f"MT5_SERVER : {SERVER}")
print(f"MT5_PATH   : {PATH or '(not set — using default)'}")
print()

try:
    import MetaTrader5 as mt5
except ImportError:
    print("ERROR: MetaTrader5 package not installed. Run: pip install MetaTrader5")
    sys.exit(1)

print(f"MetaTrader5 package version: {mt5.__version__}")

# 1. Initialize
init_kwargs = {}
if PATH:
    init_kwargs["path"] = PATH

print("\n[1] Initializing MT5 terminal...")
if not mt5.initialize(**init_kwargs):
    print(f"FAILED: mt5.initialize() error: {mt5.last_error()}")
    sys.exit(1)
print("    OK")

# 2. Login
print(f"\n[2] Logging in as {LOGIN} on {SERVER}...")
authorized = mt5.login(LOGIN, password=PASSWORD, server=SERVER)
if not authorized:
    err = mt5.last_error()
    print(f"FAILED: mt5.login() error: {err}")
    mt5.shutdown()
    sys.exit(1)
print("    OK")

# 3. Account info
print("\n[3] Account info:")
info = mt5.account_info()
if info is None:
    print(f"FAILED: mt5.account_info() returned None — {mt5.last_error()}")
else:
    print(f"    Login   : {info.login}")
    print(f"    Name    : {info.name}")
    print(f"    Server  : {info.server}")
    print(f"    Balance : {info.balance:.2f} {info.currency}")
    print(f"    Equity  : {info.equity:.2f} {info.currency}")
    print(f"    Leverage: 1:{info.leverage}")

# 4. EURUSD.a tick
SYMBOL = "EURUSD.a"
print(f"\n[4] Tick for {SYMBOL}...")
# Ensure symbol is visible in Market Watch
mt5.symbol_select(SYMBOL, True)
tick = mt5.symbol_info_tick(SYMBOL)
if tick is None:
    print(f"FAILED: no tick for {SYMBOL} — {mt5.last_error()}")
    print("       (Trying EURUSD without suffix...)")
    mt5.symbol_select("EURUSD", True)
    tick = mt5.symbol_info_tick("EURUSD")
    if tick is None:
        print(f"FAILED: no tick for EURUSD either — {mt5.last_error()}")
    else:
        print(f"    Bid: {tick.bid}  Ask: {tick.ask}  (EURUSD — no .a suffix on this server)")
else:
    spread = round((tick.ask - tick.bid) / 0.0001, 1)
    print(f"    Bid: {tick.bid}  Ask: {tick.ask}  Spread: {spread} pips")

# 5. List available symbols (filtered to forex)
print("\n[5] Available forex symbols (first 20):")
symbols = mt5.symbols_get()
if symbols:
    forex = [s.name for s in symbols if "USD" in s.name or "EUR" in s.name or "GBP" in s.name]
    for s in sorted(forex)[:20]:
        print(f"    {s}")
else:
    print(f"    FAILED: {mt5.last_error()}")

mt5.shutdown()
print("\n✓ MT5 connection test complete.")
