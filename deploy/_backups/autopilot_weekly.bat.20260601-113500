@echo off
REM Autopilot — weekly research (Sunday 18:30 UTC, after existing WeeklyResearch task)
cd /d C:\forex-engine
claude -p --dangerously-skip-permissions --max-budget-usd 5 "Load C:/forex-engine/deploy/autopilot.md and execute the weekly cycle. Working directory is C:/forex-engine. Review the past 7 days of engine activity and trades, run research_agent.py if not already run today, write proposals to logs/autopilot_proposals.md, and Telegram the owner a brief summary. You may make up to 2 parameter tunes this run."
