@echo off
setlocal
cd /d "%~dp0"
echo KQUANT Longbridge read-only market data setup
echo.
echo Revoke any credential that has appeared in a screenshot before entering a new one.
echo Credentials are stored only in your Windows user environment.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0setup_kquant_longbridge.ps1" -StartDashboard
