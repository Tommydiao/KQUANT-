param(
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

function Invoke-Checked {
  param([scriptblock]$Command, [string]$Label)
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE."
  }
}

Invoke-Checked { & $Python -m pytest -q } "Python test suite"
Invoke-Checked { & $Python scripts\verify_read_only_boundary.py } "Read-only route audit"
Invoke-Checked { & $Python scripts\verify_security.py } "Security audit"

if (-not $SkipFrontend) {
  Push-Location web
  try {
    Invoke-Checked { npm.cmd run lint } "Frontend lint"
    Invoke-Checked { npm.cmd run test } "Frontend tests"
    Invoke-Checked { npm.cmd run build } "Frontend build"
  } finally {
    Pop-Location
  }
}

Write-Host "KQUANT release-candidate verification completed." -ForegroundColor Green
