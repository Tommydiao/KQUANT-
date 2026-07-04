@echo off
setlocal
cd /d "%~dp0"
echo KQUANT local verification
echo.
echo This check builds the frontend, verifies live data / AI / safety guardrails,
echo writes outputs\monday-pilot-readiness.json and .md, and runs pytest when
echo Python is available.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0verify_kquant_local.ps1"
