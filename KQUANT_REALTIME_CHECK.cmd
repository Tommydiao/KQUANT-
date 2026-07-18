@echo off
setlocal
cd /d "%~dp0"
echo KQUANT Longbridge realtime check
echo.
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0check_kquant_realtime.ps1"
