@echo off
taskkill /FI "WINDOWTITLE eq ForexEngine*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq ForexDashboard*" /T /F >nul 2>&1
taskkill /F /IM uvicorn.exe >nul 2>&1
echo ForexEngine stopped.
