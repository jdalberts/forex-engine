@echo off
REM Autopilot — evening review (Daily 17:00 UTC, 1h after session close)
cd /d C:\forex-engine
claude -p --dangerously-skip-permissions --max-budget-usd 3 "Load C:/forex-engine/deploy/autopilot.md and execute the evening cycle. Working directory is C:/forex-engine. The trading session has just closed; review today's activity, consider at most ONE tuning change within the safety rails, send the daily Telegram summary."
