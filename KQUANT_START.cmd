@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0start_kquant_workspace.ps1" -KillExisting
