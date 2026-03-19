@echo off
cd /d "C:\Users\jalbe\OneDrive - Ahrhoff Futtergut SA (PTY) Ltd\Github\forex-engine"
start "ForexEngine" cmd /k "python engine.py --live"
timeout /t 3 /nobreak >nul
start "ForexDashboard" cmd /k "uvicorn dashboard.app:app --host 0.0.0.0 --port 8080"
