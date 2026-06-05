# Forex Engine — ON HOLD (paused 2026-06-05)

The project was deliberately put on hold on **2026-06-05**. Nothing trades, nothing
auto-launches, and no autopilot runs until it is resumed. This file explains exactly
what was switched off and how to turn it all back on.

## What "on hold" means

All scheduled tasks were **disabled** (not deleted) and both live processes were stopped:

| Scheduled task | Normal trigger | Hold state |
|----------------|----------------|------------|
| `Forex Engine` | at Administrator logon (+1 min) | Disabled |
| `MT5 AutoStart` | at Administrator logon | Disabled |
| `Forex Engine Watchdog` | every 5 min (SYSTEM) | Disabled |
| `Forex Autopilot Morning` | Mon–Fri 11:30 UTC | Disabled |
| `Forex Autopilot Evening` | daily 17:00 UTC | Disabled |
| `Forex Autopilot Weekly` | Sun 18:30 UTC | Disabled |

Processes stopped: `engine.py` (the trading engine) and `terminal64.exe` (MetaTrader 5).

Because the tasks are *disabled* rather than deleted, a reboot will NOT restart anything,
and the every-5-minute watchdog will NOT relaunch the engine.

## How to resume (one command)

Open **PowerShell as Administrator** (the tasks require elevation to change) and run:

```powershell
& 'C:\forex-engine\deploy\forex-engine-resume.ps1'
```

That re-enables all six tasks and launches MT5 + the engine. Watch `logs/engine.log`
for `MT5 authenticated` followed by `Engine running — polling every 15s`.

## Important: the broker demo may have expired

The Pepperstone **MT5 demo account expires after ~30 days of inactivity**. If, after
resuming, `logs/engine.log` shows `Broker authentication failed` / `Invalid account`:

1. Create a fresh **MT5** (not MT4) demo at pepperstone.com.
2. Update `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` in `.env`.
3. Restart MT5 + the engine (re-run the resume script).

## Manual control (if you prefer not to use the script)

```powershell
# Resume:
'Forex Engine','MT5 AutoStart','Forex Engine Watchdog','Forex Autopilot Morning','Forex Autopilot Evening','Forex Autopilot Weekly' |
  ForEach-Object { Enable-ScheduledTask -TaskName $_ }
Start-ScheduledTask -TaskName 'MT5 AutoStart'; Start-Sleep 20; Start-ScheduledTask -TaskName 'Forex Engine'

# Pause again:
& 'C:\forex-engine\deploy\forex-engine-hold.ps1'
```

## Before restarting trading — open items from the 2026-06-03 review

The bot's backtested "edge" is statistically unproven (in-sample optimization, tiny
trade counts, backtest doesn't simulate all live filters). Recommended first step on
resume is to build walk-forward out-of-sample validation before trusting it with a
funded account. See `logs/autopilot_proposals.md` for the open proposals.
