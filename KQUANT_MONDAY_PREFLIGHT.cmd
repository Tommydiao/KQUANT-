@echo off
setlocal
cd /d "%~dp0"
echo KQUANT Monday preflight
echo.
echo This starts or reuses the local backend, refreshes the AI Daily report,
echo runs the Monday readiness audit, opens the dashboard, and writes:
echo   outputs\monday-pilot-readiness.json
echo   outputs\monday-pilot-readiness.md
echo.
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0run_kquant_monday_preflight.ps1" -RestartBackend
